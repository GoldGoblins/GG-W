"""Local asset inspector and reversible scene authoring for the workbench.

The source library stays intact. One small scene document holds per-object
transforms, material settings, paint strokes and socket attachments. Images
are decoded on selection, never by the simulation or its frame transport.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import os
import struct
import uuid
from collections import OrderedDict
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QPointF, QProcess, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickImageProvider

from backend import game_engine_assets as assets
from backend import game_engine_items as items
from backend import game_asset_resources as resources
from backend.platform_support import local_file_path
from backend.platform_files import atomic_replace, is_link, secure_open, NOFOLLOW
from backend.image_admission import decode_image

SCHEMA = "gg.game-engine.asset-editor.v1"
STATE_ROOT = Path(os.environ.get("XDG_STATE_HOME", str(Path.home()/".local/state"))) / "goldgoblins/gg-ai-desktop/game-editor"
DOCUMENT_PATH = STATE_ROOT / "scene.json"
STUDY_ROOT = assets.PROJECT_ROOT / "docs/blender-learning/daxter-aaa-study"
MAX_EDITS = 256
MAX_UNDO = 32
MAX_POINTS = 2048
MAX_STROKES = 256
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_TEXTURE_SIZE = 4096
GENERATED_ROOT = STATE_ROOT / "generated"
MAX_GENERATED_BYTES = 64 * 1024 * 1024


def _discard_uv_file(path):
    """Remove only our direct generated file, including long Windows paths."""
    path=Path(path).absolute()
    if path.parent.resolve()!=GENERATED_ROOT.resolve() or is_link(path):
        raise ValueError('UV_OUTPUT_OUTSIDE_ROOT')
    value=str(path)
    if os.name=='nt' and not value.startswith('\\\\?\\'):
        value='\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value
    Path(value).unlink(missing_ok=True)


def _resource_identity(path):
    """Windows ctime is creation time; use the real NTFS change timestamp."""
    info=path.stat();changed=info.st_ctime_ns
    if os.name=='nt':
        import ctypes
        import msvcrt
        from ctypes import wintypes as w
        class BasicInfo(ctypes.Structure):
            _fields_=[('created',ctypes.c_longlong),('accessed',ctypes.c_longlong),
                      ('written',ctypes.c_longlong),('changed',ctypes.c_longlong),('attributes',w.DWORD)]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        query=kernel.GetFileInformationByHandleEx
        query.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD];query.restype=w.BOOL
        with os.fdopen(secure_open(path,os.O_RDONLY|NOFOLLOW),'rb') as handle:
            basic=BasicInfo()
            if not query(msvcrt.get_osfhandle(handle.fileno()),0,ctypes.byref(basic),ctypes.sizeof(basic)):
                raise ctypes.WinError(ctypes.get_last_error())
            info=os.fstat(handle.fileno());changed=basic.changed
    return (str(path),info.st_size,info.st_mtime_ns,changed)


def local_path(raw):
    value = str(raw or "")
    parsed = urlparse(value)
    # A Windows drive letter is a path, not a URL scheme.
    is_path = Path(value).is_absolute() and not value.lower().startswith('file:')
    if not is_path and parsed.scheme and (parsed.scheme != "file" or parsed.netloc not in ("", "localhost") or parsed.query or parsed.fragment):
        raise ValueError("Välj en lokal asset ur biblioteket.")
    path = local_file_path(value) if not is_path and parsed.scheme else Path(value)
    if not path.is_absolute():
        path = assets.PROJECT_ROOT / "qml" / path if value.startswith("assets/") else assets.ASSET_ROOT / path
    path = path.resolve()
    if not any(path.is_relative_to(root.resolve()) for root in (assets.ASSET_ROOT, STUDY_ROOT, GENERATED_ROOT)):
        raise ValueError("Asseten ligger utanför projektets bibliotek.")
    if path.suffix.lower() not in (".glb", ".gltf", ".ggmesh") or not path.is_file():
        raise ValueError("Assetfilen finns inte eller formatet stöds inte.")
    if path.stat().st_size > assets.MAX_REFERENCED_BYTES:
        raise ValueError("Asseten är för stor för den här redigeraren.")
    return path


def number(value, low=-100000, high=100000):
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Ange ett ändligt värde inom tillåtet intervall.")
    return value


def read_model(path):
    path = local_path(str(path))
    # Shared packaged buffers may be siblings of the variant directory. Study
    # and generated models have their own roots; they cannot read the library.
    root = model_root(path)
    document, raw, error = assets._read_json_document(path)
    if error or not isinstance(document, dict):
        raise ValueError("Modellens glTF-data kunde inte läsas.")
    binary = b""
    if path.suffix.lower() == ".glb":
        offset = 12
        while offset + 8 <= len(raw):
            size, kind = struct.unpack_from("<II", raw, offset)
            if kind == 0x004E4942:
                binary = raw[offset+8:offset+8+size]
            offset += 8 + size
    buffers, total = [], 0
    for row in document.get("buffers", []):
        if not isinstance(row, dict):
            raise ValueError("GLTF_BUFFER_INVALID")
        declared = int(row.get("byteLength", 0))
        remaining = assets.MAX_REFERENCED_BYTES - total
        if not 0 <= declared <= remaining:
            raise ValueError("GLTF_BUFFER_BYTE_LIMIT")
        uri = str(row.get("uri", ""))
        if not uri:
            data = binary
        elif uri.startswith("data:"):
            data = resources.data_uri(uri, remaining)
        else:
            _, data = resources.read_reference(path, uri, root, remaining)
        if len(data) < declared or len(data) > remaining:
            raise ValueError("GLTF_BUFFER_LENGTH_INVALID")
        buffers.append(data)
        total += len(data)
    return document, buffers


def model_root(path):
    return next(root.resolve() for root in (assets.ASSET_ROOT, STUDY_ROOT, GENERATED_ROOT)
                if path.is_relative_to(root.resolve()))


def accessor(document, buffers, index):
    row = document["accessors"][index]
    count = int(row["count"])
    if count > assets.MAX_VERTICES * 3:
        raise ValueError("För många element i modellens data.")
    formats = {5120:"b", 5121:"B", 5122:"h", 5123:"H", 5125:"I", 5126:"f"}
    dimensions = {"SCALAR":1, "VEC2":2, "VEC3":3, "VEC4":4, "MAT4":16}
    fmt = "<" + formats[row["componentType"]] * dimensions[row["type"]]
    size = struct.calcsize(fmt)
    result = [tuple(0 for _ in range(dimensions[row["type"]])) for _ in range(count)]
    if "bufferView" in row:
        view = document["bufferViews"][row["bufferView"]]
        buf = buffers[view.get("buffer", 0)]
        offset = int(view.get("byteOffset", 0)) + int(row.get("byteOffset", 0))
        stride = int(view.get("byteStride", size))
        result = [struct.unpack_from(fmt, buf, offset+i*stride) for i in range(count)]
    sparse = row.get("sparse")
    if sparse:
        indices = sparse["indices"]; values = sparse["values"]
        iv = document["bufferViews"][indices["bufferView"]]
        vv = document["bufferViews"][values["bufferView"]]
        ifmt = "<" + formats[indices["componentType"]]
        start_i = int(iv.get("byteOffset", 0)) + int(indices.get("byteOffset", 0))
        start_v = int(vv.get("byteOffset", 0)) + int(values.get("byteOffset", 0))
        for i in range(int(sparse["count"])):
            key = struct.unpack_from(ifmt, buffers[iv.get("buffer", 0)], start_i+i*struct.calcsize(ifmt))[0]
            result[key] = struct.unpack_from(fmt, buffers[vv.get("buffer", 0)], start_v+i*size)
    if row.get("normalized") and row["componentType"] != 5126:
        divisor = {5120:127, 5121:255, 5122:32767, 5123:65535, 5125:4294967295}[row["componentType"]]
        result = [tuple(max(-1, v/divisor) for v in record) for record in result]
    return result


class EditorImages(QQuickImageProvider):
    def __init__(self, editor):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.editor = editor

    def requestImage(self, identity, size, requested_size):
        # All bitmap data remains in RAM. A revision in the URL invalidates
        # Qt's texture cache without producing a file for each brush movement.
        key = identity.split("/", 1)[0]
        if key not in self.editor.images and key in self.editor.image_requests:
            try:
                self.editor.image_url(*self.editor.image_requests[key])
            except (ValueError,OSError,KeyError,IndexError):
                pass
        image = self.editor.images.get(key, QImage()).copy()
        if size is not None:
            size.setWidth(image.width()); size.setHeight(image.height())
        return image


class AssetEditor:
    def __init__(self, runtime, parent):
        self.runtime = runtime
        self.parent = parent
        self.document = {"schema":SCHEMA, "revision":0, "edits":{}}
        self.undo = []
        self.redo = []
        self.revision = 0
        self.saved_revision = 0
        self.selected = {}
        self.catalog = None
        self.details = OrderedDict()
        self.images = OrderedDict()
        self.detail_references = OrderedDict()
        self.image_requests = {}
        self.source_aliases = {}
        self.textures = {}
        self.material_originals = {}
        self.baselines = {}
        self.placed_ids = {}
        self.drag_document = None
        self.native_records = {}
        self.restored = False
        self.provider = None
        self.engine = None
        self.notice = ""
        self.load_error = ""
        self.uv_job = None
        self.uv_progress = {}
        if DOCUMENT_PATH.is_file():
            try:
                self._load_document()
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.load_error = "Sparade redigeringar kunde inte öppnas: " + str(exc)

    def attach_engine(self, context):
        ctx = QQmlEngine.contextForObject(context)
        engine = ctx.engine() if ctx else None
        if engine is not None and engine is not self.engine:
            self.engine = engine
            self.provider = EditorImages(self)
            engine.addImageProvider("ggasseteditor", self.provider)
            self.textures.clear()

    def _load_document(self):
        if DOCUMENT_PATH.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ValueError("Scendokumentet är för stort.")
        doc = json.loads(DOCUMENT_PATH.read_text())
        if doc.get("schema") != SCHEMA or not isinstance(doc.get("edits"), dict) or len(doc["edits"]) > MAX_EDITS:
            raise ValueError("Scendokumentets format stöds inte.")
        # Paths saved by the editor remain subject to the same library gate.
        for row in doc["edits"].values():
            if row.get("source"):
                local_path(row["source"])
            if not isinstance(row.get("materials", {}), dict):
                raise ValueError("Materialdata är felaktiga.")
            for paint in row.get("materials", {}).values():
                strokes = paint.get("strokes", [])
                if len(strokes) > MAX_STROKES or any(len(s.get("points", [])) > MAX_POINTS for s in strokes):
                    raise ValueError("Målningen överskrider storleksgränsen.")
        self.document = doc
        self.revision += 1; self.saved_revision = self.revision

    def _checkpoint(self):
        self.undo.append(copy.deepcopy(self.document))
        self.undo = self.undo[-MAX_UNDO:]
        self.redo.clear()

    def _changed(self, message):
        self.revision += 1
        self.document["revision"] = self.revision
        self.notice = message
        self.images.clear()
        self.runtime._render_snapshot_signature = None

    def _row_key(self, row):
        identity = str(row.get("id", ""))
        if identity in self.placed_ids:
            return self.placed_ids[identity]
        if identity.startswith("e-"):
            try:
                i = int(identity[2:])
                return str(self.runtime._npc_ids[i] or identity)
            except (ValueError, IndexError):
                pass
        return identity[5:] if identity.startswith("item-") else identity

    def scene_rows(self):
        with self.runtime._lock:
            rows, _, _, _ = self.runtime._render_entity_rows_locked()
            result = []
            for row in rows:
                asset = (row.get("item") or {}).get("asset") or row.get("asset") or {}
                source = self.canonical_source(str(asset.get("source", "")))
                own = self._settings(self._row_key(row), source)
                result.append({**row, "identity":self._row_key(row), "source":source,
                               "original_source":source,
                               "name":(row.get("individual") or {}).get("name") or row.get("kind", "Objekt")})
                if own.get("model_source"):
                    result[-1]["source"] = own["model_source"]
                    result[-1]["name"] = Path(unquote(urlparse(own["model_source"]).path)).stem
            for kind, groups in (("FLORA", self.runtime._flora.groups), ("NATURE", self.runtime._nature.groups)):
                seen = set()
                for group, batch in groups.items():
                    for row in batch:
                        if row["id"] in seen:
                            continue
                        seen.add(row["id"])
                        result.append({**row, "identity":row["id"], "kind":kind, "group":group,
                                       "name":row.get("species", group), "source":""})
            result.extend(self.native_records.values())
            return result

    def library(self):
        if self.catalog is None:
            result = []
            for path in sorted(assets.ASSET_ROOT.rglob("*")):
                if path.suffix.lower() not in (".glb", ".gltf", ".ggmesh"):
                    continue
                relative = path.relative_to(assets.ASSET_ROOT)
                if {"refs", "concept"}.intersection(relative.parts):
                    continue
                result.append({"id":path.as_uri(), "source":path.as_uri(), "name":path.stem,
                               "path":relative.as_posix(), "format":path.suffix[1:].upper()})
            study = STUDY_ROOT / "daxter-aaa-study.glb"
            if study.is_file():
                result.insert(0, {"id":study.as_uri(), "source":study.as_uri(), "name":"Ekorrsräv — aktuell modell",
                                  "path":"Daxter study", "format":"GLB"})
            self.catalog = result[:4096]
        return self.catalog

    def select(self, request):
        identity = str(request.get("identity", ""))
        if identity:
            row = next((r for r in self.scene_rows() if identity in (r["identity"], r["id"])), None)
            if row is None:
                raise ValueError("Objektet finns inte i den inlästa scenen.")
            self.selected = {"key":"instance:"+row["identity"], "identity":row["identity"],
                             "scope":"INSTANCE", "entity":row, "name":row["name"], "source":row["source"],
                             "original_source":row.get("original_source",row["source"])}
        else:
            path = local_path(request.get("source"))
            self.selected = {"key":"asset:"+path.as_uri(), "identity":"", "scope":"ASSET",
                             "entity":{}, "name":path.stem, "source":path.as_uri(), "original_source":path.as_uri()}
            self.selected["source"] = self.document["edits"].get(self.selected["key"],{}).get("model_source",path.as_uri())
        self.notice = ""

    def _edit(self):
        if not self.selected:
            raise ValueError("Välj en asset eller ett objekt först.")
        key = self.selected["key"]
        if key not in self.document["edits"] and len(self.document["edits"]) >= MAX_EDITS:
            raise ValueError("Scenens gräns för redigeringar är nådd.")
        return self.document["edits"].setdefault(key, {"source":self.selected.get("original_source",self.selected["source"]), "materials":{}})

    def resource_stamp(self, path):
        source_stamp = _resource_identity(path)
        cached = self.detail_references.get(path.as_uri())
        if cached is None or cached[0] != source_stamp:
            references = []
            if path.suffix.lower() != ".ggmesh":
                document, _, error = assets._read_json_document(path)
                if error or not isinstance(document, dict):
                    raise ValueError("Modellens glTF-data kunde inte läsas.")
                references = [row["uri"] for key in ("buffers", "images") for row in document.get(key, [])
                              if row.get("uri") and not row["uri"].startswith("data:")]
            cached = (source_stamp, references)
            self.detail_references[path.as_uri()] = cached
        self.detail_references.move_to_end(path.as_uri())
        while len(self.detail_references) > 8:
            self.detail_references.popitem(last=False)
        stamps = []
        for uri in cached[1]:
            candidate = resources.reference(path, uri, model_root(path), assets.MAX_REFERENCED_BYTES)
            stamps.append(_resource_identity(candidate))
        return source_stamp + tuple(stamps)

    def detail(self, source):
        if not source:
            return {"format":"PROCEDURAL", "materials":[], "uv_sets":[], "clips":[],
                    "message":"Den här modellen använder målade vertexfärger. Färg och transform kan ändras här."}
        path = local_path(source)
        stamp = self.resource_stamp(path)
        if stamp in self.details:
            self.details.move_to_end(stamp)
            return self.details[stamp]
        if path.suffix == ".ggmesh":
            with path.open("rb") as handle:
                magic, stride, nv, ni = struct.unpack("<8sIII", handle.read(20))
            result = {"format":"GGMESH", "vertices":nv, "triangles":ni//3, "materials":[], "uv_sets":[], "clips":[],
                      "message":"Kompilerad modell med vertexfärger; ingen bildtextur eller UV-karta finns i filen."}
        else:
            doc, buffers = read_model(path)
            material_rows = []
            used_materials = {p.get("material",0) for m in doc.get("meshes",[]) for p in m.get("primitives",[])}
            for i, material in enumerate(doc.get("materials", [])):
                if i not in used_materials:
                    continue
                pbr = material.get("pbrMetallicRoughness", {})
                maps = []
                for label, info in (("baseColor",pbr.get("baseColorTexture")), ("normal",material.get("normalTexture")),
                                    ("ORM",pbr.get("metallicRoughnessTexture")), ("occlusion",material.get("occlusionTexture")),
                                    ("emissive",material.get("emissiveTexture"))):
                    if info and "index" in info:
                        texture = doc["textures"][info["index"]]
                        if "source" in texture:
                            maps.append({"role":label, "image":texture["source"], "uv":int(info.get("texCoord", 0))})
                base = pbr.get("baseColorFactor", [1,1,1,1])
                material_rows.append({"index":i, "name":material.get("name", "Material "+str(i+1)), "maps":maps,
                                      "color":QColor.fromRgbF(*base).name(), "roughness":pbr.get("roughnessFactor", 1),
                                      "metalness":pbr.get("metallicFactor", 1)})
            uv_sets = {}; uv_metrics = {}; vertices = 0; triangles = 0
            for mesh in doc.get("meshes", []):
                for primitive in mesh.get("primitives", []):
                    attrs = primitive.get("attributes", {})
                    if "POSITION" not in attrs:
                        continue
                    count = int(doc["accessors"][attrs["POSITION"]]["count"]); vertices += count
                    ids = [r[0] for r in accessor(doc,buffers,primitive["indices"])] if "indices" in primitive else list(range(count))
                    if primitive.get("mode", 4) != 4:
                        continue
                    triangles += len(ids)//3
                    for name, index in attrs.items():
                        if not name.startswith("TEXCOORD_"):
                            continue
                        uv = accessor(doc,buffers,index); target = uv_sets.setdefault(name, [])
                        metric = uv_metrics.setdefault(name,{"triangles":0,"collapsed":0,"outside":0})
                        metric["outside"] += sum(not (0<=u<=1 and 0<=v<=1) for u,v in uv)
                        edges = set()
                        for j in range(0,len(ids)-2,3):
                            a,b,c = ids[j:j+3]
                            metric["triangles"] += 1
                            area = abs((uv[b][0]-uv[a][0])*(uv[c][1]-uv[a][1])-(uv[c][0]-uv[a][0])*(uv[b][1]-uv[a][1]))
                            metric["collapsed"] += area<1e-10
                            edges.update((tuple(sorted((a,b))),tuple(sorted((b,c))),tuple(sorted((c,a)))))
                        # The inspector draws a bounded wire overlay. The
                        # complete UV accessor stays in the source model.
                        for a,b in sorted(edges)[:max(0,30000-len(target))]:
                            target.append([uv[a][0],uv[a][1],uv[b][0],uv[b][1],primitive.get("material",0)])
            result = {"format":path.suffix[1:].upper(), "vertices":vertices, "triangles":triangles,
                      "meshes":len(doc.get("meshes", [])), "joints":sum(len(s.get("joints",[])) for s in doc.get("skins",[])),
                      "clips":[a.get("name", "Animation "+str(i+1)) for i,a in enumerate(doc.get("animations",[]))],
                      "materials":material_rows, "uv_sets":[{"name":k,"edges":v,"bounded":len(v)>=30000,**uv_metrics[k]} for k,v in sorted(uv_sets.items())],
                      "bytes":path.stat().st_size}
        self.details[stamp] = result
        while len(self.details) > 8:
            self.details.popitem(last=False)
        return result

    def _base_image(self, source, material_index, role):
        path = local_path(source)
        detail = self.detail(source)
        material = next((m for m in detail["materials"] if m["index"]==material_index), None)
        if not material:
            raise ValueError("Välj ett material med en bildtextur.")
        mapping = next((m for m in material["maps"] if m["role"]==role), None)
        if mapping is None:
            if role != "baseColor" or not detail.get("uv_sets"):
                raise ValueError("Materialet har ingen sådan textur.")
            image = QImage(1024,1024,QImage.Format.Format_RGBA8888)
            # A new texture multiplies the material factor. White keeps the
            # original colour until a brush stroke actually changes it.
            image.fill(Qt.GlobalColor.white)
            return image
        doc, buffers = read_model(path)
        ref = doc["images"][mapping["image"]]
        if "bufferView" in ref:
            view = doc["bufferViews"][ref["bufferView"]]
            start = int(view.get("byteOffset",0)); data = buffers[view.get("buffer",0)][start:start+view["byteLength"]]
        else:
            uri = str(ref.get("uri", ""))
            if uri.startswith("data:"):
                data = resources.data_uri(uri, assets.MAX_SOURCE_BYTES)
            else:
                _, data = resources.read_reference(path, uri, model_root(path), assets.MAX_SOURCE_BYTES)
        try:
            return decode_image(data,max_encoded_bytes=assets.MAX_SOURCE_BYTES,
                                max_dimension=MAX_TEXTURE_SIZE,
                                max_decoded_bytes=MAX_TEXTURE_SIZE*MAX_TEXTURE_SIZE*4)
        except ValueError as exc:
            raise ValueError("Texturen kunde inte öppnas eller överskrider bildens storleksgräns.") from exc

    def _settings(self, identity, source):
        # A library edit supplies defaults. Object edits override individual
        # properties; strokes compose over the library's painted texture.
        source = self.canonical_source(source)
        original_source = next((row.get("source",source) for row in self.document["edits"].values()
                                if row.get("model_source")==source),source)
        base = self.document["edits"].get("asset:"+original_source, {})
        own = self.document["edits"].get("instance:"+identity, {}) if identity else {}
        if not base and not own:
            return {}
        result = copy.deepcopy(base)
        for key,value in own.items():
            if key != "materials":
                result[key] = copy.deepcopy(value)
        mats = result.setdefault("materials", {})
        for key,value in own.get("materials", {}).items():
            before = mats.get(key, {})
            mats[key] = {**before, **copy.deepcopy(value), "strokes":before.get("strokes", [])+value.get("strokes", [])}
        return result

    def canonical_source(self, source):
        if source and source not in self.source_aliases:
            try:
                self.source_aliases[source] = local_path(source).as_uri()
            except (ValueError,OSError):
                self.source_aliases[source] = source
        return self.source_aliases.get(source,source)

    def image_url(self, identity, source, material_index, role="baseColor"):
        stamp = self.resource_stamp(local_path(source))
        token = hashlib.sha256((identity+source+str(material_index)+role+repr(stamp)).encode()).hexdigest()[:24]
        self.image_requests[token] = (identity,source,material_index,role)
        if token not in self.images:
            image = self._base_image(source,material_index,role)
            settings = self._settings(identity,source).get("materials", {}).get(str(material_index), {})
            if role == "baseColor":
                painter = QPainter(image); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                for stroke in settings.get("strokes", []):
                    colour = QColor(stroke["color"]); colour.setAlphaF(float(stroke["opacity"]))
                    pen = QPen(colour, float(stroke["size"])*image.width(), Qt.PenStyle.SolidLine,
                               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen)
                    points = [QPointF(float(p[0])*image.width(),float(p[1])*image.height()) for p in stroke["points"]]
                    if len(points)==1:
                        painter.drawPoint(points[0])
                    for a,b in zip(points,points[1:]):
                        painter.drawLine(a,b)
                painter.end()
            self.images[token] = image
            while len(self.images)>8 or (len(self.images)>1 and sum(i.sizeInBytes() for i in self.images.values())>96*1024*1024):
                self.images.popitem(last=False)
        image = self.images[token]
        return {"url":"image://ggasseteditor/"+token+"/"+str(self.revision), "width":image.width(), "height":image.height()}

    def _remember_baseline(self):
        identity = self.selected.get("identity", "")
        if not identity or identity in self.baselines:
            return
        entity = self.selected.get("entity", {})
        baseline = {k:float(entity.get(k, 1 if k in ("sx","sy","sz") else 0))
                    for k in ("x","y","z","yaw","pitch","roll","sx","sy","sz")}
        if entity.get("kind") not in ("FLORA","NATURE"):
            baseline["yaw"] = math.degrees(baseline["yaw"])
        else:
            baseline["sx"] = baseline["sy"] = baseline["sz"] = float(entity.get("scale",1))
        self.baselines[identity] = baseline

    def _restore_transforms(self):
        for identity,baseline in self.baselines.items():
            row = self.document["edits"].get("instance:"+identity,{})
            self._sync_transform(identity,{**baseline,**row.get("transform",{})})

    def restore_placements(self):
        r = self.runtime
        with r._lock:
            for entity_id,identity in list(self.placed_ids.items()):
                edit = self.document["edits"].get("instance:"+identity,{})
                if not edit.get("placement"):
                    r._despawn_entity_locked(int(entity_id[2:])); self.placed_ids.pop(entity_id,None)
            for key,edit in self.document["edits"].items():
                if not key.startswith("instance:"):
                    continue
                identity = key[9:]
                if edit.get("baseline"):
                    self.baselines.setdefault(identity,edit["baseline"])
                if edit.get("placement") and identity not in self.placed_ids.values():
                    t = edit.get("transform",{}); kind=edit["placement"]["kind"]
                    index = r._spawn_entity_locked(kind,float(t.get("x",0)),float(t.get("y",0)),float(t.get("z",0)),
                                                  (float(t.get("sx",1)),float(t.get("sy",1)),float(t.get("sz",1))),edit.get("color","#ffffff"),.5,static=True)
                    if index is not None:
                        self.placed_ids[f"e-{index:04d}"] = identity
                self._sync_transform(identity,edit.get("transform",{}))
            self.restored = True

    def attach_native_models(self):
        for attr in ("_world_tree_model","_world_places_model","_ground_cover_model"):
            model = getattr(self.parent,attr,None)
            if model is not None:
                model.asset_editor = self
                self.refresh_native(model)

    def pick_native(self, request):
        kind = str(request.get("batchKind","TREE"))
        attr = {"TREE":"_world_tree_model","PLACE":"_world_places_model","COVER":"_ground_cover_model"}.get(kind)
        model = getattr(self.parent,attr,None) if attr else None
        key = str(request.get("batchKey","")); index=int(request.get("index",-1))
        group = next((row for row in model.rows if row["key"]==key),None) if model else None
        if group is None:
            raise ValueError("Den valda kartasseten finns inte i den inlästa sidan.")
        entry = model.cached[group["base"]]; table=entry["table"]
        raw = bytes(getattr(table,"_asset_editor_base",table._buffer))
        if not 0<=index<len(raw)//80:
            raise ValueError("Kartobjektet är inte längre inläst.")
        values=struct.unpack_from("<20f",raw,index*80)
        sx=math.sqrt(sum(values[k]**2 for k in (0,4,8))); sy=math.sqrt(sum(values[k]**2 for k in (1,5,9))); sz=math.sqrt(sum(values[k]**2 for k in (2,6,10)))
        identity="map:"+kind+":"+group["base"]+":"+str(index)
        mesh_key=entry.get("mesh_species",entry["species"])+":"+str(group["lod"])
        mesh_path=model.meshes.assets/(mesh_key.replace(":","-lod") if model.meshes.assets.name=="flora" else mesh_key.replace(":","-"))
        mesh_path=mesh_path.with_suffix(".ggmesh")
        self.native_records[identity]={"id":identity,"identity":identity,"kind":"MAP_ASSET","name":entry["species"],
            "source":mesh_path.as_uri() if mesh_path.is_file() else "", "x":values[3],"y":values[7],"z":values[11],
            "sx":sx,"sy":sy,"sz":sz,"yaw":math.atan2(values[2]/max(sz,.001),values[0]/max(sx,.001)),
            "native":{"kind":kind,"base":group["base"],"index":index,"origin":[values[3],values[7],values[11]]}}
        self.select({"identity":identity})

    def refresh_native(self, model, force=False):
        if not force and getattr(model,"_asset_editor_revision",-1)==self.revision:
            return
        from PySide6.QtCore import QByteArray
        edits = [(key,row) for key,row in self.document["edits"].items() if row.get("native")]
        native_kind = next((kind for attr,kind in (("_world_tree_model","TREE"),("_world_places_model","PLACE"),("_ground_cover_model","COVER"))
                            if getattr(self.parent,attr,None) is model),"")
        for base,entry in model.cached.items():
            table=entry["table"]
            relevant=[row for key,row in edits if row["native"]["base"]==base and row["native"]["kind"]==native_kind]
            if not relevant and not hasattr(table,"_asset_editor_base"):
                continue
            if not hasattr(table,"_asset_editor_base"):
                table._asset_editor_base=bytes(table._buffer)
            buf=bytearray(table._asset_editor_base)
            for row in relevant:
                native=row["native"]; index=int(native["index"])
                if not 0<=index<len(buf)//80:
                    continue
                values=list(struct.unpack_from("<20f",buf,index*80))
                if any(abs(values[k]-v)>.1 for k,v in zip((3,7,11),native["origin"])):
                    continue  # A regenerated map page must not retarget a different object.
                t=row.get("transform",{})
                for key,offset in (("x",3),("y",7),("z",11)):
                    if key in t:values[offset]=t[key]
                scales=[math.sqrt(sum(values[k]**2 for k in offsets)) for offsets in ((0,4,8),(1,5,9),(2,6,10))]
                for n,(key,offsets) in enumerate((("sx",(0,4,8)),("sy",(1,5,9)),("sz",(2,6,10)))):
                    factor=float(t.get(key,scales[n]))/max(.001,scales[n])
                    for k in offsets:values[k]*=factor
                if any(k in t for k in ("yaw","pitch","roll")):
                    from backend.game_engine_ecology_render import instance_bytes
                    transform={"x":values[3],"y":values[7],"z":values[11],"scale":1,
                               "yaw":t.get("yaw",math.degrees(math.atan2(values[2],values[0]))),"pitch":t.get("pitch",0),"roll":t.get("roll",0)}
                    matrix=struct.unpack("<20f",instance_bytes(transform))
                    for n,offsets in enumerate(((0,4,8),(1,5,9),(2,6,10))):
                        for k in offsets:values[k]=matrix[k]*float(t.get(("sx","sy","sz")[n],scales[n]))
                if row.get("color"):
                    colour=QColor(row["color"])
                    for k,v in zip((12,13,14),(colour.redF(),colour.greenF(),colour.blueF())):
                        values[k]*=v*(v*(v*.305306011+.682171111)+.012522878)
                if row.get("hidden"):
                    for k in (0,1,2,4,5,6,8,9,10):values[k]=0
                struct.pack_into("<20f",buf,index*80,*values)
            table._buffer=QByteArray(bytes(buf)); table.markDirty()
        model._asset_editor_revision=self.revision

    def _sync_transform(self, identity, values):
        # Native simulation pools receive the same transform as the renderer.
        # Flora/nature use their persistent identity override on batch rebuild.
        r = self.runtime
        with r._lock:
            placed = next((key for key,value in self.placed_ids.items() if value==identity), "")
            if placed:
                index = int(placed[2:])
            elif identity.startswith("e-"):
                index = int(identity[2:])
            elif identity == "player":
                index = 0
            else:
                index = next((i for i in r._active_entity_indices if r._npc_ids[i]==identity), -1)
            if 0 <= index < len(r._alive) and r._alive[index]:
                for key,value in values.items():
                    if key in ("x","y","z","yaw","pitch","roll","sx","sy","sz"):
                        getattr(r,"_"+key)[index] = math.radians(value) if key=="yaw" else value
                r._vx[index]=r._vy[index]=r._vz[index]=0
                if r._kind[index]=="NPC":
                    r._npc_home_x[index]=r._x[index]; r._npc_home_z[index]=r._z[index]
                if any(k in values for k in ("sx","sy","sz")):
                    r._radius[index] = max(.05, max(r._sx[index],r._sz[index])*.5)
                if hasattr(r,"_grid_dirty"):
                    r._grid_dirty = True
            elif identity in r._item_instances:
                instance = r._item_instances[identity]
                if instance.get("location") == "GROUND":
                    instance.setdefault("position", {}).update({k:v for k,v in values.items() if k in ("x","y","z")})

    def decorate(self, snapshot):
        self.attach_native_models()
        if not isinstance(snapshot,dict) or not self.document["edits"]:
            return snapshot
        render = snapshot.get("render")
        if not isinstance(render,dict) or "entities" not in render:
            return snapshot
        result = dict(snapshot); result["render"] = dict(render); rows = []
        for original in render["entities"]:
            identity = self._row_key(original)
            asset = (original.get("item") or {}).get("asset") or original.get("asset") or {}
            settings = self._settings(identity,str(asset.get("source", "")))
            if not settings:
                rows.append(original); continue
            row = dict(original)
            own = self.document["edits"].get("instance:"+identity, {})
            # Pool positions remain live during play. Only proxies without a
            # simulation slot need a renderer position override.
            transform = own.get("transform", {})
            if transform and row.get("asset"):
                row["asset"]={**row["asset"],"editor_scale":True}
            if not str(original["id"]).startswith("e-"):
                row.update({k:v for k,v in transform.items() if k in ("x","y","z","sx","sy","sz","pitch","roll")})
                if "yaw" in transform:
                    row["yaw"] = math.radians(transform["yaw"])
            if "color" in settings:
                row["color"] = settings["color"]
            if own.get("hidden"):
                row["hidden"] = True
            if settings.get("model_source"):
                changed_asset = dict(asset); changed_asset.update(settings.get("model_binding",{})); changed_asset["source"] = settings["model_source"]
                changed_asset["mode"] = "AUTHORED_SKINNED" if row.get("kind") in ("PLAYER","NPC","ACTOR") else "AUTHORED_STATIC"
                changed_asset["status"] = "READY"
                changed_asset["editor_model"] = True
                changed_asset["instance_rank"] = asset.get("instance_rank", 0)
                changed_asset["instance_budget"] = asset.get("instance_budget", 32)
                clips = changed_asset.get("clips", [])
                idle = next((c.get("name","") for c in clips if isinstance(c,dict) and "idle" in str(c.get("name","")).lower()), "")
                changed_asset["clip"] = idle; changed_asset["runtime_clip"] = idle
                changed_asset["clip_status"] = "READY" if idle else "ROOT_POSE_ONLY"
                row["asset"] = changed_asset
                if row.get("item"):
                    row["item"] = {**row["item"], "asset":changed_asset}
            gear = self._gear_rows(identity,settings.get("gear", {}))
            if "gear" in settings:
                replaced = set(settings["gear"])
                row["equipment"] = [g for g in row.get("equipment", []) if g.get("equipped_slot") not in replaced]+gear
            rows.append(row)
        result["render"]["entities"] = rows
        return result

    def batch(self, rows, revision):
        output = []
        for original in rows:
            settings = self.document["edits"].get("instance:"+original["id"], {})
            if settings.get("hidden"):
                continue
            if not settings:
                output.append(original); continue
            row = dict(original); transform = settings.get("transform", {})
            row.update({k:v for k,v in transform.items() if k in ("x","y","z","yaw","pitch","roll")})
            if "sx" in transform:
                row["scale"] = transform["sx"]
            if settings.get("color"):
                row["editor_color"] = settings["color"]
            output.append(row)
        return output, (int(revision)<<20)+self.revision

    def _gear_rows(self, identity, gear):
        result = []
        for slot,definition_id in gear.items():
            if not definition_id:
                continue
            definition = items.definition(self.runtime._item_catalog, definition_id)
            if not definition:
                continue
            instance = items.make_instance(self.runtime._item_catalog, "editor-"+identity+"-"+slot, definition_id,
                                           location="EQUIPPED", owner_id=identity)
            instance["equipped_slot"] = slot
            row = items.instance_view(self.runtime._item_catalog,instance)
            row["asset"] = assets.item_binding(self.runtime._asset_catalog,row.get("visual",{}).get("asset_id", ""),
                                               0,row["kind"],appearance_index=items.item_appearance_index(instance["instance_id"]))
            result.append(row)
        return result

    def material(self, loader, identity):
        if loader is None:
            return {"ok":True,"materials":[]}
        raw_source = loader.property("source")
        source = raw_source.toString() if isinstance(raw_source,QUrl) else str(raw_source or "")
        settings = self._settings(identity,source)
        material_rows = []
        if settings.get("materials") or settings.get("color"):
            for ordinal,material in enumerate(self.detail(source).get("materials",[])):
                index = material["index"]
                values = copy.deepcopy(settings.get("materials",{}).get(str(index),{}))
                values.pop("strokes",None)
                if "color" in settings:
                    values.setdefault("color",settings["color"])
                if settings.get("materials",{}).get(str(index),{}).get("strokes"):
                    values["image"] = self.image_url(identity,source,index)["url"]
                material_rows.append({"index":index,"ordinal":ordinal,"name":material["name"],"values":values})
        return {"ok":True,"materials":material_rows}

    def _install_uv_artifact(self, staged, target, old_detail, selected, original, expected_revision):
        """Prepare all fallible state before making a generated model visible."""
        staged,target=Path(staged),Path(target)
        for path in (staged,target):
            if path.parent.resolve()!=GENERATED_ROOT.resolve() or is_link(path):
                raise ValueError('UV_OUTPUT_OUTSIDE_ROOT')
        if self.revision!=expected_revision:
            raise ValueError("Scenen ändrades under UV-arbetet. Försök igen från den aktuella scenen.")
        doc,raw,error=assets._read_json_document(staged)
        if error or not isinstance(doc,dict):
            raise ValueError("UV-atlasens modell kunde inte läsas.")
        # The trusted exporter produces a self-contained static GLB. Do not
        # publish external resources, a replacement rig or animation tracks.
        sections=[doc.get(section,[]) for section in ('buffers','images')]
        if any(not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows) for rows in sections):
            raise ValueError("UV-atlasens resursdata är felaktiga.")
        if doc.get('skins') or doc.get('animations') or any(row.get('uri') for rows in sections for row in rows):
            raise ValueError("UV-atlasen måste vara en fristående statisk GLB.")
        binding=assets._validate_document(staged,raw,doc,target.stem)
        if binding.get('status')!='READY':
            raise ValueError("Den förberedda modellen kunde inte laddas.")
        detail=self.detail(staged.as_uri())
        used=sum(p.stat().st_size for p in GENERATED_ROOT.glob('*.glb')
                 if p not in (staged,target) and not is_link(p))
        if used+len(raw)>MAX_GENERATED_BYTES:
            raise ValueError("Atlasen överskrider lagringsgränsen på 64 MiB.")
        if selected['key'] not in self.document['edits'] and len(self.document['edits'])>=MAX_EDITS:
            raise ValueError("Scenens gräns för redigeringar är nådd.")
        binding['source']=target.as_uri()
        binding['relative_source']='assets/'+target.name
        document=copy.deepcopy(self.document)
        edit=document['edits'].setdefault(selected['key'],{'source':original,'materials':{}})
        by_name={m['name']:edit.get('materials',{}).get(str(m['index']),{}) for m in old_detail.get('materials',[])}
        edit['materials']={str(m['index']):by_name[m['name']] for m in detail['materials'] if by_name.get(m['name'])}
        edit.update(model_source=target.as_uri(),model_binding=binding)
        selection=copy.deepcopy(self.selected)
        if selection.get('key')==selected['key']:selection['source']=target.as_uri()
        revision=self.revision+1;document['revision']=revision
        undo=(self.undo+[copy.deepcopy(self.document)])[-MAX_UNDO:]
        message="UV-atlasen är klar. Modellens form och befintliga färger är bevarade."
        # No callbacks, parsers or native work run between publication and the
        # prepared assignments. A failed rename leaves the prior scene intact.
        if staged!=target:atomic_replace(staged,target)
        self.document=document;self.undo=undo;self.redo=[];self.selected=selection
        self.revision=revision;self.notice=message;self.images=OrderedDict()
        self.runtime._render_snapshot_signature=None
        self.uv_progress={'busy':False,'percent':100,'stage':message}

    def prepare_uv(self):
        if self.uv_job is not None:
            raise ValueError("En UV-atlas förbereds redan.")
        if self.runtime._running:
            raise ValueError("Pausa innan du förbereder UV.")
        source = local_path(self.selected.get("source",""))
        if source.suffix not in (".glb",".gltf"):
            raise ValueError("Välj modellens GLB i biblioteket för UV-förberedelse.")
        old_detail = self.detail(source.as_uri())
        if old_detail.get("joints") or old_detail.get("clips"):
            raise ValueError("Riggade och animerade modeller använder sin befintliga UV. UV-arbetet får inte ändra deras rigg.")
        settings = self._settings(self.selected.get("identity",""),source.as_uri())
        if any(m.get("strokes") for m in settings.get("materials",{}).values()):
            raise ValueError("Förbered UV före målning. Befintliga penseldrag måste behålla sin UV-layout.")
        GENERATED_ROOT.mkdir(parents=True,exist_ok=True)
        token = hashlib.sha256(b"paint-atlas-v2"+source.read_bytes()+repr(self.resource_stamp(source)).encode()).hexdigest()[:24]
        target = GENERATED_ROOT/(token+".glb")
        selected = copy.deepcopy(self.selected)
        original = selected.get("original_source",source.as_uri())
        expected_revision=self.revision
        if target.is_file():
            try:
                self._install_uv_artifact(target,target,old_detail,selected,original,expected_revision)
                return
            except (ValueError,OSError,KeyError,IndexError,TypeError,RuntimeError):
                _discard_uv_file(target)
        from backend.blender_contract import blender_bin
        blender=blender_bin()
        if not blender or not Path(blender).is_file():
            raise ValueError("Blender behövs för att packa UV-atlasen.")
        if sum(p.stat().st_size for p in GENERATED_ROOT.glob("*.glb"))>=MAX_GENERATED_BYTES:
            raise ValueError("UV-atlasernas lagringsgräns på 64 MiB är nådd.")
        pending = target.with_name(target.stem+'.'+uuid.uuid4().hex+'.pending.glb')
        process=QProcess(self.parent); self.uv_job=process
        self.uv_progress={"busy":True,"percent":0,"stage":"Startar UV-förberedelse"}
        stream=bytearray()
        def read_progress():
            stream.extend(bytes(process.readAllStandardOutput()))
            while b"\n" in stream:
                line,_,tail=stream.partition(b"\n"); stream[:]=tail
                if line.startswith(b"GGUV "):
                    try:
                        row=json.loads(line[5:]); self.uv_progress.update(row)
                    except (ValueError,UnicodeDecodeError):
                        pass
            if len(stream)>8192:stream.clear()
        timer=QTimer(process);timer.setSingleShot(True)
        def finished(code, status):
            if self.uv_job is not process:return
            timer.stop();read_progress();self.uv_job=None
            try:
                if code!=0 or not pending.is_file() or self.uv_progress.get("error"):
                    raise ValueError(self.uv_progress.get("error","UV-förberedelsen kunde inte slutföras."))
                self._install_uv_artifact(pending,target,old_detail,selected,original,expected_revision)
            except (ValueError,OSError,KeyError,IndexError,TypeError,RuntimeError) as exc:
                self.uv_progress={"busy":False,"error":str(exc),"stage":str(exc)}
            finally:
                _discard_uv_file(pending);process.deleteLater()
        def timeout():
            self.uv_progress["error"]="UV-förberedelsen tog för lång tid och avbröts."
            process.kill()
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(read_progress)
        process.finished.connect(finished)
        process.errorOccurred.connect(lambda error: finished(-1,None) if error==QProcess.ProcessError.FailedToStart else None)
        timer.timeout.connect(timeout);timer.start(90000)
        process.start(str(blender),["-t","4","--background","--factory-startup","--python",
                      str(assets.PROJECT_ROOT/"tools/blender/prepare_game_asset_uv.py"),"--",str(source),str(pending)])

    def response(self, request, context, loader=None):
        self.attach_engine(context)
        if not self.restored:
            self.restore_placements()
        self.attach_native_models()
        op = str(request.get("op", "OPEN")).upper()
        if self.uv_job is not None and op not in ("OPEN","REFRESH","IMAGE","UV_STATUS","SELECT","SELECT_ASSET","PICK_BATCH","APPLY_MATERIAL"):
            raise ValueError("Vänta tills UV-förberedelsen är klar innan du ändrar eller sparar scenen.")
        changed = False
        if op == "APPLY_MATERIAL":
            return self.material(loader,str(request.get("identity", "")))
        if op == "PICK_BATCH":
            self.pick_native(request)
        elif op in ("SELECT", "SELECT_ASSET"):
            self.select(request)
        elif op == "PREPARE_UV":
            self.prepare_uv(); changed = not self.uv_progress.get("busy")
        elif op == "PLACE" or op == "DUPLICATE":
            if self.runtime._running:
                raise ValueError("Pausa simuleringen innan du placerar objekt.")
            source = self.selected.get("source", "")
            if not source:
                raise ValueError("Välj en modell i biblioteket för placering eller duplicering.")
            path = local_path(source)
            if path.suffix==".ggmesh":
                raise ValueError("Placera den kompilerade modellen via dess GLB i biblioteket.")
            doc,raw,error = assets._read_json_document(path)
            binding = assets._validate_document(path,raw,doc,path.stem)
            if binding.get("status") != "READY":
                raise ValueError("Modellen kan inte placeras: "+str((binding.get("error") or {}).get("message","Ogiltig modell")))
            if len(self.placed_ids)>=128 or len(self.document["edits"])>=MAX_EDITS:
                raise ValueError("Scenens gräns för placerade assets är nådd.")
            r = self.runtime; current = self.selected.get("entity", {})
            source_edit = copy.deepcopy(self.document["edits"].get(self.selected["key"],{}))
            transform = {k:float(current.get(k,1 if k in ("sx","sy","sz") else 0)) for k in ("pitch","yaw","roll","sx","sy","sz")}
            transform["yaw"] = math.degrees(transform["yaw"])
            transform.update(source_edit.get("transform",{}))
            x=float(current.get("x",r._x[0]))+1.5; z=float(current.get("z",r._z[0]))+1.5
            y=float(current["y"]) if op=="DUPLICATE" and "y" in current else r._terrain_height_locked(x,z)+(.65 if binding.get("skinned") else 0)
            transform.update(x=x,y=y,z=z)
            with r._lock:
                index = r._spawn_entity_locked("ACTOR" if binding.get("skinned") else "PROP",x,y,z,
                    tuple(transform[k] for k in ("sx","sy","sz")),"#ffffff",.5,static=True)
            if index is None:
                raise ValueError("Scenens objektpool är full.")
            identity = "editor-object-"+str(max([int(v.rsplit("-",1)[-1]) for v in self.placed_ids.values()]+[0])+1)
            self._checkpoint(); self.placed_ids[f"e-{index:04d}"] = identity
            source_edit.update(source=source,model_source=source,model_binding=binding,
                               placement={"kind":"ACTOR" if binding.get("skinned") else "PROP"},transform=transform)
            self.document["edits"]["instance:"+identity] = source_edit
            self._sync_transform(identity,transform)
            self.selected={"key":"instance:"+identity,"identity":identity,"scope":"INSTANCE",
                           "entity":{"id":f"e-{index:04d}","identity":identity,"x":x,"y":y,"z":z,"kind":"ACTOR" if binding.get("skinned") else "PROP"},
                           "name":path.stem,"source":source}
            self._changed("Asseten är placerad i scenen."); changed=True
        elif op == "VISIBILITY":
            if self.runtime._running or not self.selected.get("identity"):
                raise ValueError("Pausa och välj ett scenobjekt först.")
            self._checkpoint(); self._edit()["hidden"]=bool(request.get("hidden",True))
            if self.selected.get("entity",{}).get("native"):
                self._edit()["native"]=self.selected["entity"]["native"]
            self._changed("Objektets synlighet är ändrad."); changed=True
        elif op == "BEGIN_TRANSFORM":
            if self.runtime._running or not self.selected.get("identity"):
                raise ValueError("Välj ett objekt och pausa innan du drar det.")
            self._remember_baseline()
            self.drag_document = copy.deepcopy(self.document)
            self._checkpoint()
            edit=self._edit()
            edit["baseline"]=self.baselines.get(self.selected["identity"],{})
            if self.selected.get("entity",{}).get("native"):
                edit["native"]=self.selected["entity"]["native"]
            return {"ok":True,"preview":True}
        elif op in ("DRAG_PREVIEW","END_TRANSFORM","CANCEL_TRANSFORM"):
            if self.drag_document is None:
                return {"ok":True,"preview":True}
            if op=="DRAG_PREVIEW":
                values = {k:number(v) for k,v in request.get("values",{}).items() if k in ("x","y","z")}
                self._edit().setdefault("transform",{}).update(values)
                self._sync_transform(self.selected["identity"],values)
                for attr in ("_world_tree_model","_world_places_model","_ground_cover_model"):
                    model=getattr(self.parent,attr,None)
                    if model:self.refresh_native(model,force=True)
                self.runtime._render_snapshot_signature = None
                return {"ok":True,"preview":True}
            if op=="CANCEL_TRANSFORM":
                self.document = self.drag_document
                if self.undo:
                    self.undo.pop()
            self.drag_document = None
            self._restore_transforms()
            self._changed("Objektet är flyttat." if op=="END_TRANSFORM" else "Flyttningen är avbruten."); changed=True
        elif op == "TRANSFORM":
            if not self.selected.get("identity"):
                raise ValueError("Välj ett objekt i scenen för att flytta det.")
            if self.runtime._running:
                raise ValueError("Pausa simuleringen innan du flyttar objekt.")
            values = {k:number(v,.01,100) if k in ("sx","sy","sz") else number(v)
                      for k,v in request.get("values", {}).items() if k in ("x","y","z","yaw","pitch","roll","sx","sy","sz")}
            self._remember_baseline()
            self._checkpoint(); edit = self._edit(); edit["baseline"]=self.baselines[self.selected["identity"]]
            edit.setdefault("transform",{}).update(values)
            if self.selected.get("entity",{}).get("native"):
                edit["native"]=self.selected["entity"]["native"]
            self._sync_transform(self.selected["identity"],values)
            self._changed("Objektets transform är ändrad."); changed = True
        elif op == "MATERIAL":
            colour = str(request.get("color", ""))
            if colour and not QColor(colour).isValid():
                raise ValueError("Ange en giltig färg, till exempel #e6bd74.")
            values = {k:number(v,0,1) if k in ("roughness","metalness") else number(v,-32,32)
                      for k,v in request.items() if k in ("roughness","metalness","positionU","positionV","scaleU","scaleV")}
            if colour:
                values["color"] = QColor(colour).name()
            self._checkpoint()
            if self.selected.get("entity",{}).get("native"):
                self._edit()["native"]=self.selected["entity"]["native"]
            if request.get("material", -1)==-1:
                self._edit()["color"] = values.get("color", "#ffffff")
            else:
                self._edit().setdefault("materials",{}).setdefault(str(int(request["material"])),{}).update(values)
            self._changed("Materialet är ändrat."); changed = True
        elif op == "PAINT":
            material_index = int(request["material"])
            self._base_image(self.selected["source"],material_index,"baseColor")
            points = request.get("points", [])
            if not 1 <= len(points) <= MAX_POINTS:
                raise ValueError("Penseldraget är för långt.")
            colour = QColor(str(request.get("color", "")))
            if not colour.isValid():
                raise ValueError("Penselns färg är ogiltig.")
            stroke = {"points":[[number(p[0],0,1),number(p[1],0,1)] for p in points],
                      "size":number(request.get("size",.025),.001,.25), "opacity":number(request.get("opacity",1),.01,1),
                      "color":colour.name()}
            existing = self.document["edits"].get(self.selected["key"],{}).get("materials",{}).get(str(material_index),{}).get("strokes",[])
            if len(existing)>=MAX_STROKES:
                raise ValueError("Målningens gräns för penseldrag är nådd.")
            self._checkpoint(); self._edit().setdefault("materials",{}).setdefault(str(material_index),{}).setdefault("strokes",[]).append(stroke)
            self._changed("Penseldraget är applicerat på texturen."); changed = True
        elif op == "GEAR":
            slot = str(request.get("slot", "MAIN_HAND")); definition_id = str(request.get("definition", ""))
            if self.selected.get("entity",{}).get("kind") not in ("PLAYER","NPC","ACTOR") and not self.detail(self.selected.get("source","")).get("joints"):
                raise ValueError("Gear behöver en karaktär med en rigg.")
            if definition_id and slot not in items.allowed_equip_slots(self.runtime._item_catalog,definition_id):
                raise ValueError("Den utrustningen passar inte i vald slot.")
            self._checkpoint(); gear = self._edit().setdefault("gear", {})
            if definition_id:
                gear[slot] = definition_id
            else:
                gear[slot] = ""
            self._changed("Karaktärens gear är ändrad."); changed = True
        elif op == "RESET_SELECTED":
            self._checkpoint(); self.document["edits"].pop(self.selected.get("key",""),None)
            self._restore_transforms()
            self.restore_placements()
            self._changed("Objektets redigeringar är återställda."); changed = True
        elif op in ("UNDO", "REDO"):
            source,target = (self.undo,self.redo) if op=="UNDO" else (self.redo,self.undo)
            if source:
                target.append(copy.deepcopy(self.document)); self.document = source.pop()
                self._changed("Ändringen är ångrad." if op=="UNDO" else "Ändringen är återgjord.")
                self._restore_transforms()
                self.restore_placements()
                changed = True
        elif op == "SAVE":
            data = json.dumps(self.document,ensure_ascii=False,separators=(",", ":")).encode()
            if len(data)>MAX_DOCUMENT_BYTES:
                raise ValueError("Scendokumentet överskrider storleksgränsen.")
            STATE_ROOT.mkdir(parents=True,exist_ok=True)
            temporary = DOCUMENT_PATH.with_suffix(".tmp")
            with temporary.open("wb") as handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno())
            temporary.replace(DOCUMENT_PATH)
            self.saved_revision = self.revision; self.notice = "Scen och assetredigeringar är sparade."
        elif op == "LOAD":
            if self.runtime._running:
                raise ValueError("Pausa innan du öppnar sparade redigeringar.")
            self._checkpoint(); self._load_document(); self.images.clear()
            self.restore_placements(); self._restore_transforms()
            self.notice = "Sparade redigeringar är öppnade."; changed = True
        elif op not in ("OPEN", "REFRESH", "IMAGE", "UV_STATUS"):
            raise ValueError("Redigeringskommandot stöds inte.")
        selected = dict(self.selected)
        if selected:
            own = self.document["edits"].get(selected["key"],{})
            effective = self._settings(selected.get("identity",""),selected.get("original_source",selected.get("source","")))
            selected["source"] = effective.get("model_source",selected.get("original_source",selected.get("source","")))
            self.selected["source"] = selected["source"]
            selected["detail"] = self.detail(selected.get("source", ""))
            selected["edit"] = copy.deepcopy(self.document["edits"].get(selected["key"], {}))
            if selected.get("identity"):
                current = next((r for r in self.scene_rows() if r["identity"]==selected["identity"]),selected["entity"])
                selected["entity"] = current
            if request.get("material") is not None and request.get("material",-1)>=0:
                try:
                    selected["image"] = self.image_url(selected.get("identity",""),selected["source"],int(request["material"]),str(request.get("role","baseColor")))
                except ValueError as exc:
                    selected["image_error"] = str(exc)
        gear_options = []
        for definition_id,definition in self.runtime._item_catalog.get("items",{}).items():
            if definition.get("equip_slot") or definition.get("gear",{}).get("slot"):
                gear_options.append({"id":definition_id,"name":definition.get("name",definition_id),
                                     "slots":items.allowed_equip_slots(self.runtime._item_catalog,definition_id)})
        result = {"ok":True, "revision":self.revision, "dirty":self.revision!=self.saved_revision,
                  "undo":len(self.undo), "redo":len(self.redo), "selected":selected,
                  "notice":self.notice or self.load_error, "gear":gear_options, "uv_job":self.uv_progress}
        if op in ("OPEN","REFRESH","SELECT","SELECT_ASSET","PICK_BATCH","LOAD") or changed:
            result["library"] = self.library()
            result["scene"] = [{k:r.get(k) for k in ("id","identity","name","kind","source","x","y","z")}
                               for r in self.scene_rows()]
        if changed or op=="UV_STATUS" and not self.uv_progress.get("busy"):
            result["snapshot"] = self.decorate(self.runtime.snapshot())
        return result


def editor_for(host):
    value = getattr(host,"_game_asset_editor",None)
    if value is None:
        from backend import game_engine_host
        value = AssetEditor(game_engine_host._RUNTIME,host)
        host._game_asset_editor = value
    return value


def dispatch(host, context, loader, raw):
    try:
        if len(raw)>160000:
            raise ValueError("Redigeringskommandot är för stort.")
        request = json.loads(raw)
        return json.dumps(editor_for(host).response(request,context,loader),ensure_ascii=False,separators=(",", ":"))
    except (ValueError, OSError, KeyError, IndexError, TypeError, AttributeError, RuntimeError, struct.error) as exc:
        return json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False)
