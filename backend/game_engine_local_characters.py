"""Local character selection and durable saves for the actual GG simulation."""
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory
import copy,json,os,stat,tempfile,uuid
from backend.platform_support import file_locks as fcntl
from pathlib import Path
from PySide6.QtCore import QObject,Property,Signal,Slot,QTimer,QCoreApplication
from backend import game_engine_mmo as mmo,game_engine_character_creation as appearance

ROOT=Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/'goldgoblins/gg-ai-desktop/game/local-characters'
SCHEMA='gg.local-characters.v1'
MAX_BYTES=8*1024*1024

def atomic(path,value):
    if path.is_symlink():raise ValueError('Sparfilen får inte vara en symbolisk länk.')
    data=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    if len(data)>MAX_BYTES:raise ValueError('Karaktärens sparfil är för stor.')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(prefix='.character-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as file:file.write(data);file.flush();os.fsync(file.fileno())
        os.replace(name,path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)
    return len(data)

def read(path):
    if path.is_symlink():raise ValueError('Sparfilen får inte vara en symbolisk länk.')
    if not path.is_file():return None
    with path.open('rb') as file:data=file.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:raise ValueError('Karaktärens sparfil är för stor.')
    return json.loads(data)

def validate_payload(payload):
    if not isinstance(payload,dict) or payload.get('schema')!=mmo.PERSISTENCE_SCHEMA or payload.get('version')!=1:raise ValueError('Ogiltigt sparformat.')
    for key in ('player','inventory','progression'):
        if not isinstance(payload.get(key),dict):raise ValueError('Sparfilen saknar '+key+'.')
    # Reject NaN/Infinity accepted by Python's JSON reader before touching the
    # simulation, and use the same size bound for memory and disk snapshots.
    if len(json.dumps(payload,allow_nan=False,separators=(',',':')).encode())>MAX_BYTES:raise ValueError('Karaktärens sparfil är för stor.')

class CharacterStore:
    """Same save/load contract as the runtime's MemoryStateStore, with atomic IO."""
    def __init__(self,root,decorate=None,*,before_save=None,before_load=None):
        self.root=Path(root);self._revision=0;self.decorate=decorate
        self.before_save=before_save;self.before_load=before_load
    mode='LOCAL_FILE'
    def path(self,key):
        if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Ogiltig lokal karaktär.')
        path=self.root/(key+'.json')
        if path.is_symlink():raise ValueError('Sparfilen får inte vara en symbolisk länk.')
        if not path.resolve().is_relative_to(self.root.resolve()):raise ValueError('Sparfilen ligger utanför karaktärsmappen.')
        return path
    def save(self,key,payload):
        validate_payload(payload)
        value=copy.deepcopy(payload)
        if self.decorate:value.update(self.decorate())
        if self.before_save:self.before_save(key,value)
        revision=self._revision+1
        size=atomic(self.path(key),{'schema':'gg.local-character-save.v1','revision':revision,'payload':value})
        self._revision=revision
        return {'schema':mmo.PERSISTENCE_SCHEMA,'key':key,'revision':revision,'bytes':size,'mode':self.mode}
    def load(self,key):
        if self.before_load:self.before_load()
        value=read(self.path(key))
        if value is None:return None
        if not isinstance(value,dict) or value.get('schema')!='gg.local-character-save.v1' or not isinstance(value.get('payload'),dict):raise ValueError('Ogiltigt sparformat.')
        validate_payload(value['payload'])
        revision=value.get('revision')
        if type(revision) is not int or not 1<=revision<2**63:raise ValueError('Ogiltig sparrevision.')
        self._revision=max(self._revision,revision)
        return copy.deepcopy(value['payload'])
    @property
    def revision(self):return self._revision

class LocalCharacters(QObject):
    changed=Signal()
    worldReady=Signal()
    loggedOut=Signal()
    def __init__(self,parent=None,*,root=None,runtime=None):
        super().__init__(parent)
        if runtime is None:
            from backend import game_engine_host
            runtime=game_engine_host._RUNTIME
        self.runtime=runtime;self.root=Path(root) if root else ROOT;self._custody=None
        self.store=CharacterStore(self.root,self._appearance,before_save=self._guard_custody_save,before_load=self._recover_custody)
        presentation=getattr(parent,'_game_presentation',None)
        if presentation:
            presentation.local_character_mode=True
            if presentation.lua and presentation.character_key is None:presentation.lua.saving_enabled=False
        self.rows=[];self.active_id='';self.error='';self.phase='LOGIN';self._closed=False;self._registry_valid=True;self._initialized=False;self._session_lock=None
        self._base_store=runtime._state_store;self._base_key=runtime._persistence_key
        self._base_name=getattr(runtime,'_local_character_name','Gold Goblin')
        self._read_registry()
        self.timer=QTimer(self);self.timer.setInterval(60000);self.timer.timeout.connect(self._autosave)
        app=QCoreApplication.instance()
        if app:app.aboutToQuit.connect(self.close)
    def _read_registry(self):
        try:
            value=read(self.root/'characters.json')
            if value is not None:
                if not isinstance(value,dict) or value.get('schema')!=SCHEMA or not isinstance(value.get('characters'),list) or len(value['characters'])>10:raise ValueError('Ogiltigt karaktärsregister.')
                rows=[];ids=set();names=set()
                for row in value['characters']:
                    self.store.path(row['id']);name=self._name(row['name']);selection=appearance.normalize(row['selection'])
                    level=row.get('level',1)
                    if row['id'] in ids or name.casefold() in names or type(level) is not int or not 1<=level<=60:raise ValueError('Ogiltigt karaktärsregister.')
                    ids.add(row['id']);names.add(name.casefold());rows.append({'id':row['id'],'name':name,'selection':selection,'level':level})
                self.rows=rows;self._initialized=True
            else:self.rows=[];self._initialized=False
            self._registry_valid=True
        except (OSError,ValueError,KeyError,TypeError) as error:
            self._registry_valid=False;self.phase='ERROR';self.error='Karaktärsregistret kunde inte läsas: '+str(error)[:180]
    def _acquire_lock(self):
        if self._session_lock is not None:return
        if self.root.is_symlink():raise ValueError('Karaktärsmappen får inte vara en symbolisk länk.')
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=secure_open(self.root/'.session.lock',os.O_RDWR|os.O_CREAT|NOFOLLOW|CLOEXEC,0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('Ogiltig låsfil för karaktärerna.')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('En annan lokal spelklient använder karaktärerna. Stäng den och öppna karaktärsvalet igen.') from None
            self._session_lock=os.fdopen(fd,'r+b');fd=None
            from backend.game_engine_local_custody import LocalCustodyStore
            self._custody=LocalCustodyStore(self.root,session_lock=self._session_lock)
            self._recover_custody()
            # A second client may have been constructed before the first one
            # saved. Reload only after exclusive ownership; never publish its
            # stale roster or migrate the first character twice.
            self._read_registry()
        finally:
            if fd is not None:os.close(fd)
    def _release_lock(self):
        if self._session_lock is not None:
            if getattr(self.runtime,'_local_custody_store',None) is self._custody:
                self.runtime._local_custody_store=None;self.runtime._local_character_id=''
            self._custody=None
            self._session_lock.close();self._session_lock=None
    def _guard_custody_save(self,key,payload):
        if self._custody is not None:
            pending=self._custody._path('shared-custody.pending.json')
            if pending.exists() or getattr(self.runtime,'_local_custody_recovery_blocked',False):
                raise ValueError('LOCAL_CUSTODY_RECOVERY_REQUIRED')
            self._custody.validate_save(key,payload)
    def _recover_custody(self):
        if self._custody is None:return
        result=self._custody.recover()
        if result.get('character_deleted'):
            self.rows=result['rows'];self._initialized=True
        retirement=getattr(self,'_pending_local_retirement','')
        if retirement:
            final=self._delete_with_custody(retirement)
            self.rows=final['rows'];self._initialized=True
        active=getattr(self.runtime,'_local_character_id','')
        if active and (result.get('status')=='COMMITTED' or getattr(self.runtime,'_local_custody_recovery_blocked',False)):
            with self.runtime._lock:
                envelope=self._custody.snapshot()['characters'][active]
                self.runtime._apply_local_custody_locked(envelope)
        return result
    def _delete_with_custody(self,identity):
        from backend.game_engine_local_custody import RecoveryRequired
        try:
            final=self._custody.delete_character(identity)
        except RecoveryRequired:
            # Even unlink+directory-fsync uncertainty is forward-only. Keep
            # this target for the next action if recovery is still unavailable.
            self._pending_local_retirement=identity
            self._custody.recover()
            final=self._custody.delete_character(identity)
        self._pending_local_retirement=''
        return final
    @staticmethod
    def _name(value):
        if not isinstance(value,str) or not 1<=len(value.strip())<=24 or any(ord(c)<32 for c in value):raise ValueError('Namnet får ha 1–24 tecken.')
        return value.strip()
    def _appearance(self):return {'character_appearance':copy.deepcopy(self.runtime._character_creation)}
    @Property('QVariantMap',notify=changed)
    def state(self):
        return {'phase':self.phase,'characters':copy.deepcopy(self.rows),'active_id':self.active_id,'error':self.error,'local':True}
    @Property('QVariantMap',constant=True)
    def catalog(self):return appearance.catalog()
    @Slot('QVariantMap',result='QVariantMap')
    def previewCharacter(self,selection):
        try:
            selection=appearance.normalize(selection or self.catalog['defaults'])
            return {'catalog':self.catalog,'selection':selection,'preview':appearance.preview(selection)}
        except (OSError,ValueError,TypeError) as error:return {'error':str(error)[:240]}
    def _registry(self):
        if self._session_lock is None:raise ValueError('Öppna karaktärsvalet först.')
        if not self._registry_valid:raise ValueError('Det skadade karaktärsregistret måste återställas före sparning.')
        atomic(self.root/'characters.json',{'schema':SCHEMA,'characters':self.rows});self._initialized=True
    @Slot(result=bool)
    def open(self):
        try:
            self.runtime.pause()
            self._acquire_lock()
            if not self._registry_valid:raise ValueError('Karaktärsregistret kunde inte läsas. Befintliga filer har bevarats.')
            self._closed=False
            if self.active_id and not self.logout():return False
            if not self._initialized:
                with self.runtime._lock:
                    self.runtime.save_state();payload=self.runtime._state_store.load(self.runtime._persistence_key)
                    selection=self.runtime._character_creation or appearance.catalog()['defaults']
                identity=uuid.uuid4().hex;self.store.save(identity,payload)
                self.rows=[{'id':identity,'name':'Äventyrare','selection':copy.deepcopy(selection),'level':int(payload.get('progression',{}).get('level',1))}]
                try:self._registry()
                except Exception:self.rows=[];self.store.path(identity).unlink(missing_ok=True);raise
            self.timer.stop()
            # Failed post-commit unlink can only leave these own tombstones;
            # retries are bounded and never inspect unrelated files.
            for path in self.root.glob('.deleted-*'):
                if len(path.name)==41 and all(c in '0123456789abcdef' for c in path.name[9:]) and not path.is_symlink():
                    identity=path.name[9:]
                    if any(row['id']==identity for row in self.rows):
                        target=self.store.path(identity)
                        if not target.exists():os.replace(path,target)
                        continue
                    try:path.unlink()
                    except OSError:pass
            self.phase='CHARACTERS';self.error='';self.changed.emit();return True
        except (OSError,ValueError,KeyError,TypeError) as error:
            if not self._registry_valid:self._release_lock()
            self.error=str(error)[:240];self.changed.emit();return False
    @Slot(str,'QVariantMap',result=bool)
    def create(self,name,selection):
        try:
            self._recover_custody()
            name=self._name(name);selection=appearance.normalize(selection);appearance.preview(selection)
            if self.phase!='CHARACTERS' or not self._registry_valid or self._session_lock is None:raise ValueError('Öppna karaktärsvalet först.')
            if len(self.rows)>=10:raise ValueError('Du kan ha högst tio lokala karaktärer.')
            if any(r['name'].casefold()==name.casefold() for r in self.rows):raise ValueError('Det namnet används redan.')
            from backend.game_engine_host import GameEngineRuntime
            fresh=GameEngineRuntime()
            try:
                fresh._character_creation=selection;fresh.save_state();payload=fresh._state_store.load(fresh._persistence_key)
            finally:fresh.shutdown()
            payload['character_appearance']=selection;identity=uuid.uuid4().hex
            # This save belongs to a fresh runtime; avoid the active avatar's
            # appearance decorator when writing its initial snapshot.
            initial=CharacterStore(self.root);initial.save(identity,payload)
            row={'id':identity,'name':name,'selection':selection,'level':1};self.rows.append(row)
            try:self._registry()
            except Exception:self.rows.pop();self.store.path(identity).unlink(missing_ok=True);raise
            self.error='';self.changed.emit();return True
        except (OSError,ValueError,KeyError,TypeError) as error:self.error=str(error)[:240];self.changed.emit();return False
    @Slot(str,result=bool)
    def enter(self,identity):
        try:
            if self.phase!='CHARACTERS' or not self._registry_valid or self._session_lock is None:raise ValueError('Öppna karaktärsvalet först.')
            row=next((r for r in self.rows if r['id']==identity),None)
            if row is None:raise ValueError('Karaktären finns inte.')
            payload=self.store.load(identity)
            if payload is None:raise ValueError('Sparfilen saknas.')
            selection=appearance.normalize(payload.get('character_appearance') or row['selection']);appearance.preview(selection)
            if self.active_id and self.active_id!=identity:self._save()
            with self.runtime._lock:
                previous_store=self.runtime._state_store;previous_key=self.runtime._persistence_key
                previous_appearance=copy.deepcopy(self.runtime._character_creation)
                previous_name=getattr(self.runtime,'_local_character_name',self._base_name)
                previous_custody=getattr(self.runtime,'_local_custody_store',None)
                previous_identity=getattr(self.runtime,'_local_character_id','')
                self.runtime.save_state()
                self.runtime._state_store=self.store;self.runtime._persistence_key=identity
                self.runtime._local_custody_store=self._custody;self.runtime._local_character_id=identity
                try:
                    result=self.runtime.load_state()
                    if result.get('error'):raise ValueError(result['error'])
                    self.runtime._vx[0]=self.runtime._vy[0]=self.runtime._vz[0]=0.
                    self.runtime._character_creation=selection;self.runtime._local_character_name=row['name']
                    presentation=getattr(self.parent(),'_game_presentation',None)
                    self.runtime._clear_local_ui_sessions_locked()
                    self.runtime._render_snapshot_cache=None;self.runtime._render_snapshot_signature=None;self.runtime._ui_snapshot_base=None
                    if presentation and not presentation.set_character(identity,initial_snapshot=self.runtime.ui_snapshot()):
                        raise ValueError('Karaktärens gränssnitt kunde inte öppnas.')
                except Exception:
                    self.runtime._state_store=previous_store;self.runtime._persistence_key=previous_key
                    self.runtime._local_custody_store=previous_custody;self.runtime._local_character_id=previous_identity
                    self.runtime.load_state();self.runtime._character_creation=previous_appearance
                    self.runtime._local_character_name=previous_name;self.runtime._ui_snapshot_base=None;raise
            self.active_id=identity;self.phase='WORLD';self.error='';self.timer.start();self.changed.emit();self.worldReady.emit();return True
        except (OSError,ValueError,KeyError,TypeError) as error:self.error=str(error)[:240];self.changed.emit();return False
    def _save(self):
        if not self.active_id:return
        self._recover_custody()
        presentation=getattr(self.parent(),'_game_presentation',None)
        if presentation:presentation.save_character_ui(self.active_id)
        with self.runtime._lock:
            self.runtime.save_state()
            row=next(r for r in self.rows if r['id']==self.active_id)
            row['selection']=copy.deepcopy(self.runtime._character_creation or row['selection']);row['level']=int(self.runtime._progression.get('level',1))
        self._registry()
    def _autosave(self):
        if self.phase!='WORLD' or self._closed:return
        try:self._save();self.error=''
        except (OSError,ValueError,TypeError) as error:self.error=str(error)[:240]
        self.changed.emit()
    @Slot(result=bool)
    def logout(self):
        try:
            self.runtime.pause();self._save();self.timer.stop()
            if self.active_id:
                presentation=getattr(self.parent(),'_game_presentation',None)
                if presentation and not presentation.set_character(None):raise ValueError('Gränssnittsinställningarna kunde inte sparas vid utloggning.')
                with self.runtime._lock:
                    payload=self.store.load(self.active_id)
                    self._base_store.save(self._base_key,payload)
                    self.runtime._state_store=self._base_store;self.runtime._persistence_key=self._base_key
                    self.runtime._persistence_revision=self._base_store.revision
                    self.runtime._local_character_name=self._base_name;self.runtime._ui_snapshot_base=None
                    self.runtime._local_custody_store=None;self.runtime._local_character_id=''
                    self.runtime._clear_local_ui_sessions_locked()
                self.active_id=''
            self.phase='CHARACTERS';self.error=''
            # Logout can run inside QML Window.onClosing. Rebuilding the
            # focused login tree from that same closing stack can block Qt's
            # scene synchronization. Announce only after the caller returns;
            # a completed close or a newer entry must not reopen the menu.
            QTimer.singleShot(0,self._announce_logout)
            return True
        except (OSError,ValueError,TypeError) as error:self.error=str(error)[:240];self.changed.emit();return False
    @Slot()
    def _announce_logout(self):
        if not self._closed and self.phase=='CHARACTERS' and not self.active_id:
            self.changed.emit();self.loggedOut.emit()
    @Slot(str,str,result=bool)
    def delete(self,identity,confirmation):
        try:
            self._recover_custody()
            if self.phase!='CHARACTERS' or self._session_lock is None or identity==self.active_id:raise ValueError('Öppna karaktärsvalet och logga ut före borttagning.')
            row=next((r for r in self.rows if r['id']==identity and r['name']==confirmation),None)
            if row is None:raise ValueError('Skriv rätt karaktärsnamn.')
            if self._custody is not None:
                if not self._custody.can_delete(identity,include_history=False)['allowed']:
                    raise ValueError('Karaktären har kvar post, auktioner eller guildåtaganden. Slutför dem före borttagning.')
                result=self._delete_with_custody(identity)
                self.rows=result['rows'];self._initialized=True
                self.error='';self.changed.emit();return True
            path=self.store.path(identity);tombstone=self.root/('.deleted-'+identity)
            if tombstone.exists() or tombstone.is_symlink():raise ValueError('Karaktärens borttagning måste slutföras först.')
            moved=path.exists()
            if moved:os.replace(path,tombstone)
            previous=self.rows;self.rows=[r for r in self.rows if r is not row]
            try:self._registry()
            except Exception:
                self.rows=previous
                if moved:os.replace(tombstone,path)
                raise
            if moved:
                try:tombstone.unlink()
                except OSError:pass
            self.error='';self.changed.emit();return True
        except (OSError,ValueError,TypeError) as error:self.error=str(error)[:240];self.changed.emit();return False
    @Slot(result=bool)
    def close(self):
        if self._closed:return True
        if self.active_id and not self.logout():return False
        self.timer.stop();self._closed=True;self._release_lock();return True

def characters_for(host):
    if not hasattr(host,'_local_characters'):host._local_characters=LocalCharacters(host)
    return host._local_characters
