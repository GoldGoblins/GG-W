"""Finite local intro over the live GG camera, with the original start/skip API."""
import math

KEYS=((0.,12.,-12.,-160.),(4.,9.,-18.,-100.),(8.,5.,-7.,-30.),(12.,5.55,-10.,0.))


class OpeningCinematicMixin:
    def _opening_cinematic_command_locked(self,row):
        if row['op']=='CinematicStop':
            self._stop_opening_cinematic_locked();return []
        if row['op']!='CinematicStart':raise ValueError('CINEMATIC_COMMAND_UNKNOWN')
        if self._opening_cinematic:return []
        self._travel_idle_locked()
        if self._services['duel']:raise ValueError('DUEL_IN_PROGRESS')
        if self._movement_mode!='GROUND' or not self._grounded or self._replaying:raise ValueError('CINEMATIC_GROUND_REQUIRED')
        self._opening_cinematic=dict(elapsed=0.,restore=self._camera_pose_locked())
        self._legacy_held.clear();self._legacy_autorun=False;self._legacy_jump=False;self._follow_id=''
        self._actions.auto_attack=False
        self._input.update(forward=0.,throttle=0.,strafe=0.,turn=0.,steer=0.,vertical=0.,jump=False,grapple=False,boost=False)
        self._vx[0]=self._vz[0]=0.
        self._apply_camera_view_locked(KEYS[0][1:])
        return []

    def _stop_opening_cinematic_locked(self):
        record=getattr(self,'_opening_cinematic',None)
        if record:
            self._opening_cinematic=None;self._apply_camera_view_locked(record['restore'])

    def _tick_opening_cinematic_locked(self,dt):
        record=self._opening_cinematic
        if not record:return
        if type(dt) not in (int,float) or not math.isfinite(dt) or not 0<=dt<=1.:raise ValueError('CINEMATIC_CLOCK_INVALID')
        if self._player_defeated_locked() or self._services.get('taxi_flight') or self._vehicle_kind!='NONE' or self._movement_mode!='GROUND':
            self._stop_opening_cinematic_locked();return
        record['elapsed']+=dt
        if record['elapsed']>=KEYS[-1][0]:self._stop_opening_cinematic_locked();return
        start,end=next((a,b) for a,b in zip(KEYS,KEYS[1:]) if a[0]<=record['elapsed']<b[0])
        t=(record['elapsed']-start[0])/(end[0]-start[0]);smooth=t*t*(3-2*t)
        self._apply_camera_view_locked([a+(b-a)*smooth for a,b in zip(start[1:],end[1:])])

    def _opening_cinematic_view_locked(self):
        record=self._opening_cinematic
        return dict(active=bool(record),elapsed=round(record['elapsed'],4) if record else 0.,duration=KEYS[-1][0],
                    source='GG_LOCAL_INTRO_CAMERA',music_suppressed=bool(record))
