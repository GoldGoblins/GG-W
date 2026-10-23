import json,os,sys,time,tempfile
os.environ['QT_QPA_PLATFORM']='offscreen'
# All spawned CLI fixtures and bitmap guards must use test-owned homes.
_TEST_HOME=tempfile.TemporaryDirectory(prefix='gg-gpt-tui-test-')
os.environ['GG_DESKTOP_STATE_ROOT']=os.path.join(_TEST_HOME.name,'state')
os.environ['GG_USER_CODEX_HOME']=os.path.join(_TEST_HOME.name,'user-codex')
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from pathlib import Path
from unittest.mock import patch
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent
from PySide6.QtCore import QUrl,QObject
from backend.chat_surface_host import ChatSurfaceHost
from backend.desktop_settings import normalize_settings
assert normalize_settings({"engineTarget":"GPT_TUI"})["engineTarget"] == "GPT_TUI"
app=QGuiApplication([])
engine=QQmlEngine()
for name in ['Main.qml','components/ContextComposer.qml','components/SettingsChatModule.qml','components/TelemetryRail.qml']:
 c=QQmlComponent(engine,QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'qml' / name)))
 assert not c.isError(), [e.toString() for e in c.errors()]
print('QML compilation PASS')
from backend.codex_wallet import (
 CODEX_SESSIONS,
 DESKTOP_CODEX_SESSIONS,
 snapshot as codex_wallet_snapshot,
)
with tempfile.TemporaryDirectory() as d:
 wallet_session=Path(d)/'wallet.jsonl'
 wallet_session.write_text(json.dumps({'payload':{'type':'token_count','info':{'total_token_usage':{'total_tokens':10},'last_token_usage':{'input_tokens':8,'total_tokens':9},'model_context_window':100},'rate_limits':{'primary':{'used_percent':4.0,'resets_at':4102444800},'secondary':{'used_percent':0.0}}}})+'\n')
 wallet=codex_wallet_snapshot(wallet_session)
 assert wallet['live_tokens'] == 4
 assert wallet['live_reset_at'] == 4102444800
 assert wallet['live_reset_label'] != '—'
print('GPT wallet LIVE bar/reset data PASS')
class Grid:
 def __init__(self): self.output=b''
 def feed_bytes(self,b): self.output+=b
 def reset_terminal(self): self.reset_count=getattr(self,'reset_count',0)+1
host=ChatSurfaceHost();host._gpt_grid=Grid();host._gpt_size=(80,24)
host._sessions['ws.tui.gpt']={'master':123}
with patch('backend.chat_surface_host.os.write') as write:
 for chunk in ['/', 'model', '\n', 'hej / världen', '\n']:
  assert host.writeChatTerminal('ws.tui.gpt',chunk)
 assert b''.join(call.args[1] for call in write.call_args_list) == b'/model\nhej / v\xc3\xa4rlden\n'
del host._sessions['ws.tui.gpt']
host._track_gpt_input('/flush\n')
assert host._commands_from_gpt_output("Unrecognized command '/flu") == []
assert host._commands_from_gpt_output("sh'. Type '/' for commands.") == ['/flush']
assert host._commands_from_gpt_output("nothing more") == []
host._track_gpt_input("/remember it's mine\n")
assert host._commands_from_gpt_output("Unrecognized command '/remember'.") == ["/remember it's mine"]
print('GPT slash input/native commands/split local command detection PASS')

# `/new` must switch GPTUI before its terminating Enter reaches the old PTY.
host._sessions['ws.tui.gpt'] = {'master': 123}
host._gpt_session_id = 'old-session'
with patch.object(host, '_start_fresh_gpt_session', return_value=True) as fresh, patch(
    'backend.chat_surface_host.os.write'
) as write:
    assert host.writeChatTerminal('ws.tui.gpt', '/')
    assert host.writeChatTerminal('ws.tui.gpt', 'new')
    assert host.writeChatTerminal('ws.tui.gpt', '\n')
    fresh.assert_called_once_with()
    assert [call.args[1] for call in write.call_args_list] == [b'/', b'new']
del host._sessions['ws.tui.gpt']
print('GPT /new pre-Enter session switch PASS')

# The same command must be recognized when it arrives as a bracketed paste.
host._sessions['ws.tui.gpt'] = {'master': 123}
with patch.object(host, '_start_fresh_gpt_session', return_value=True) as fresh, patch(
    'backend.chat_surface_host.os.write'
) as write:
    assert host.writeChatTerminal('ws.tui.gpt', '\x1b[200~/new\x1b[201~')
    assert host.writeChatTerminal('ws.tui.gpt', '\r')
    fresh.assert_called_once_with()
    assert [call.args[1] for call in write.call_args_list] == [
        b'\x1b[200~/new\x1b[201~'
    ]
del host._sessions['ws.tui.gpt']
print('GPT bracketed /new pre-Enter switch PASS')

# VT terminal replies must not contaminate the command scanner's current line.
host._sessions['ws.tui.gpt'] = {'master': 123}
with patch.object(host, '_start_fresh_gpt_session', return_value=True) as fresh, patch(
    'backend.chat_surface_host.os.write'
) as write:
    assert host.writeChatTerminal('ws.tui.gpt', '\x1b[?1;2c')
    assert host.writeChatTerminal('ws.tui.gpt', '/new')
    assert host.writeChatTerminal('ws.tui.gpt', '\n')
    fresh.assert_called_once_with()
    assert [call.args[1] for call in write.call_args_list] == [
        b'\x1b[?1;2c', b'/new'
    ]
del host._sessions['ws.tui.gpt']
print('GPT terminal-reply isolation PASS')

# Some Codex versions keep rollout JSONL in ~/.codex/sessions even when
# CODEX_HOME points at GPTUI's isolated state directory.  The capture pass
# must adopt that new file instead of leaving the previous session active.
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    desktop_root = root / 'desktop' / 'sessions'
    shared_root = root / 'shared' / 'sessions'
    desktop_root.mkdir(parents=True)
    shared_root.mkdir(parents=True)
    existing = shared_root / 'existing.jsonl'
    existing.write_text(json.dumps({'payload': {'session_id': '00000000-0000-0000-0000-000000000001'}}) + '\n')
    created = shared_root / 'created.jsonl'
    created.write_text(json.dumps({'payload': {'session_id': '00000000-0000-0000-0000-000000000002'}}) + '\n')
    capture_host = ChatSurfaceHost()
    capture_host._sessions['ws.tui.gpt'] = {}
    capture_host._gpt_started_at = time.time() - 1
    capture_host._gpt_capture_root = desktop_root
    capture_host._gpt_capture_roots = (desktop_root, shared_root)
    capture_host._gpt_capture_before = {existing}
    with patch.object(capture_host, '_adopt_gpt_session') as adopt:
        capture_host._capture_gpt_session()
        adopt.assert_called_once_with(
            '00000000-0000-0000-0000-000000000002', sessions_root=shared_root
        )
    capture_host._close('ws.tui.gpt')
print('GPT new-session capture across Codex roots PASS')

# Adoption must publish the shared catalog immediately so the QML CHATS rail
# receives the new current row, not only the persisted session pointer.
with tempfile.TemporaryDirectory() as d:
    from backend import chat_sessions

    catalog = Path(d) / 'chat-sessions.json'
    adopted_id = '00000000-0000-0000-0000-000000000006'
    listed = []
    list_host = ChatSurfaceHost()
    list_host._gpt_session_id = ''
    list_host._legacy_gpt_session_id = ''
    list_host._sessions['ws.tui.gpt'] = {}
    list_host.chatSessionsChanged.connect(listed.append)
    with patch.object(chat_sessions, 'CATALOG_PATH', catalog), \
         patch('backend.chat_surface_host.save_codex_session_id', return_value=adopted_id), \
         patch('backend.chat_surface_host.grok_wallet_snapshot', return_value={}), \
         patch('backend.chat_surface_host.codex_wallet_snapshot', return_value={}):
        list_host._adopt_gpt_session(adopted_id, sessions_root=Path(d) / 'sessions')
    assert listed
    rows = json.loads(listed[-1])
    assert any(
        row['session_id'] == adopted_id
        and row['engine'] == 'GPT_TUI'
        and row['current'] is True
        for row in rows
    )
    list_host.shutdown()
print('GPT session adoption publishes CHATS row PASS')

# A rollout can be delayed until after the first user turn.  The capture
# watcher remains alive during its bounded capture window, but does not keep
# scanning forever once the PTY is idle.
class LiveProc:
 def poll(self): return None

with tempfile.TemporaryDirectory() as d:
 delayed_root=Path(d)/'sessions'
 delayed_root.mkdir(parents=True)
 delayed_host=ChatSurfaceHost()
 delayed_host._sessions['ws.tui.gpt']={'proc':LiveProc()}
 delayed_host._gpt_started_at=time.time()-1
 delayed_host._gpt_capture_root=delayed_root
 delayed_host._gpt_capture_roots=(delayed_root,)
 delayed_host._gpt_capture_before=set()
 delayed_host._gpt_capture_deadline=time.monotonic()+5
 with patch.object(delayed_host._gpt_capture_timer,'start') as start:
  delayed_host._capture_gpt_session()
  start.assert_called_once_with(500)
 delayed_host._gpt_capture_timer.stop()
 delayed_host._sessions.pop('ws.tui.gpt', None)
print('GPT delayed rollout capture keeps watching PASS')

from backend import gpt_memory_commands
with tempfile.TemporaryDirectory() as d:
 root=Path(d)
 desktop_root=root/'desktop'/'sessions'
 shared_root=root/'shared'/'sessions'
 desktop_state=root/'desktop'/'active-session.json'
 legacy_state=root/'legacy-session.json'
 desktop_root.mkdir(parents=True)
 shared_root.mkdir(parents=True)
 active='00000000-0000-0000-0000-000000000003'
 parent='00000000-0000-0000-0000-000000000004'
 active_session=shared_root/'active.jsonl'
 parent_session=shared_root/'parent.jsonl'
 active_session.write_text(json.dumps({'payload':{'session_id':active}})+'\n')
 parent_session.write_text(json.dumps({'payload':{'session_id':parent}})+'\n')
 desktop_state.write_text(json.dumps({'session_id':active}))
 legacy_state.write_text(json.dumps({'session_id':parent}))
 with patch.object(gpt_memory_commands,'DESKTOP_CODEX_SESSION_STATE',desktop_state), \
      patch.object(gpt_memory_commands,'DESKTOP_CODEX_SESSIONS',desktop_root), \
      patch.object(gpt_memory_commands,'CODEX_SESSION_STATE',legacy_state), \
      patch.object(gpt_memory_commands,'CODEX_SESSIONS',shared_root):
  assert gpt_memory_commands._session_path() == active_session
print('GPT /flush follows active GPTUI pointer across Codex roots PASS')

with tempfile.TemporaryDirectory() as d:
 memory_root=Path(d)/'memory';session=Path(d)/'session.jsonl'
 rows=[
  {'type':'response_item','payload':{'type':'message','role':'developer','content':[{'type':'input_text','text':'hidden'}]}},
  {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'hello'}]}},
  {'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'world'}]}},
 ]
 session.write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
 with patch('backend.gpt_memory_commands._session_path',return_value=session), patch('backend.gpt_memory_commands._write_root',return_value=memory_root):
  result=gpt_memory_commands.run('/flush')
 assert '(1 prompts, 1 replies)' in result,result
 saved=list((memory_root/'sessions').glob('*.md'))
 assert len(saved)==1 and 'hello' in saved[0].read_text() and 'world' in saved[0].read_text()
print('GPT /flush transcript persistence PASS')
with tempfile.TemporaryDirectory() as d:
 exe=Path(d)/'codex';exe.write_text('#!/usr/bin/python3\nimport sys\nprint("GPT_TEST_READY",flush=True)\nfor line in sys.stdin:\n print("ECHO:"+line,flush=True)\n');exe.chmod(0o755)
 with patch('backend.chat_surface_host.shutil.which',return_value=str(exe)), \
      patch.object(host, '_gptui_developer_instructions', return_value='hidden profile'):
  host._gpt_session_id = ''
  host._start_gpt_tui();proc=host._sessions['ws.tui.gpt']['proc']
  assert 'developer_instructions="hidden profile"' in proc.args
  assert '--dangerously-bypass-approvals-and-sandbox' in proc.args
  assert '--sandbox' not in proc.args
  assert '--ask-for-approval' not in proc.args
  assert host._gpt_sessions_root == DESKTOP_CODEX_SESSIONS
  assert host._gpt_capture_roots == (DESKTOP_CODEX_SESSIONS, CODEX_SESSIONS)
  host._start_gpt_tui();assert host._sessions['ws.tui.gpt']['proc'] is proc
  host._resize_gpt_tui(100,40)
  host.writeChatTerminal('ws.tui.gpt','hej\n')
  until=time.monotonic()+2
  while time.monotonic()<until and b'ECHO:hej' not in host._gpt_grid.output:
   app.processEvents();time.sleep(.01)
  assert b'ECHO:hej' in host._gpt_grid.output,host._gpt_grid.output
  old_proc=proc
  host.writeChatTerminal('ws.tui.gpt','/new\n')
  new_proc=host._sessions['ws.tui.gpt']['proc']
  assert new_proc is not old_proc
  assert host._gpt_grid.reset_count == 1
  host._close('ws.tui.gpt')
  new_proc.wait(timeout=3)
  old_proc.wait(timeout=3)

# A resumed GPTUI must keep its rollout watcher armed for later session
# handoffs as well.
with tempfile.TemporaryDirectory() as d:
 root=Path(d)
 shared_home=root/'shared-home'
 shared_root=shared_home/'sessions'
 shared_root.mkdir(parents=True)
 sid='00000000-0000-0000-0000-000000000005'
 existing=shared_root/'existing.jsonl'
 existing.write_text(json.dumps({'payload':{'session_id':sid}})+'\n')
 resume_exe=root/'codex'
 resume_exe.write_text('#!/usr/bin/python3\nimport sys\nfor line in sys.stdin: pass\n')
 resume_exe.chmod(0o755)
 resume_host=ChatSurfaceHost();resume_host._gpt_grid=Grid();resume_host._gpt_size=(80,24)
 resume_host._gpt_session_id=sid
 with patch.object(resume_host,'_gpt_session_location',return_value=(shared_home,shared_root)), \
      patch('backend.chat_surface_host.prepare_codex_resume',return_value={'status':'unchanged'}), \
      patch('backend.chat_surface_host.shutil.which',return_value=str(resume_exe)):
  assert resume_host._start_gpt_tui()
  assert resume_host._gpt_capture_roots == (shared_root,)
  assert existing in resume_host._gpt_capture_before
  resume_proc=resume_host._sessions['ws.tui.gpt']['proc']
  assert '--dangerously-bypass-approvals-and-sandbox' in resume_proc.args
  assert '--sandbox' not in resume_proc.args
  assert '--ask-for-approval' not in resume_proc.args
  resume_host._close('ws.tui.gpt')
  resume_proc.wait(timeout=3)
 resume_host._gpt_grid=None;resume_host.shutdown()
print('GPT resumed-session rollout watcher PASS')
host._gpt_grid=None;host.shutdown()
host_src=Path(__import__('backend.chat_surface_host',fromlist=['__file__']).__file__).read_text()
assert '"--no-alt-screen"' in host_src
print('GPT PTY start, reuse, input/output, resize, cleanup PASS')
