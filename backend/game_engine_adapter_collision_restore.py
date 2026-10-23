"""Restore retained resident triangles after a supervised asset worker restart."""
def restore(stream,reader):
    count=0
    for key,page in tuple(stream.pages.items()):
        seen=set();groups={key:[]};instances={p['prop_key']:p.get('instance') for p in page.metadata.get('props',[])}
        for cell in tuple(page.surface.cells.values()):
            for triangle in cell:
                identity=id(triangle)
                if identity in seen:continue
                seen.add(identity);a,b,c,row=triangle
                if not page.surface.enabled(row):continue
                owner=instances.get(row.get('prop_key')) or key
                groups.setdefault(owner,[]).append((a,b,c))
        for owner,triangles in groups.items():
            try:
                reader.request('collision_begin',key=owner,triangles=len(triangles))
                for at in range(0,len(triangles),128):reader.request('collision_append',key=owner,triangles=triangles[at:at+128],timeout=3)
                reader.request('collision_commit',key=owner)
                count+=1
            except Exception:
                try:reader.request('collision_abort')
                except Exception:pass
                raise
    stream.collision_restores+=1;stream.restored_collision_pages=count
