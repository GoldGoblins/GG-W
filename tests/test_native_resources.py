"""Explicit resource contracts; real process acceptance remains in platform gates."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import io
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import gg_native_resources as resources,gg_consensus as native
from backend import gg_protocol_node as protocol,gg_posix_native as posix


def server(**changes):
    value=dict(mode="SERVER",go_max_procs=32,verify_workers=32,go_heap_bytes=256*resources.MiB,
        process_memory_bytes=512*resources.MiB,virtual_bytes=8*resources.GiB,open_files=1024,
        owner_memory_bytes=1024*resources.MiB,owner_cpu_basis_points=10000,maximum_native_children=6)
    value.update(changes)
    return resources.NativeResources(**value)


def settings():
    return {"listen_host":"127.0.0.1","max_inbound":0,"max_outbound":1,"p2p_port":23450,
        "peers":[{"host":"127.0.0.1","port":23451,"id":"1"*40}]}


class NativeResourceContractTests(unittest.TestCase):
    def test_low_defaults_keep_exact_existing_budgets_and_reject_ambient_escalation(self):
        self.assertIs(resources.resolve(),resources.LOW)
        self.assertEqual(resources.LOW.environment(),{"GOMAXPROCS":"2","GOMEMLIMIT":"256MiB"})
        self.assertEqual(resources.LOW.verify_workers,8)
        self.assertEqual(resources.LOW.ready()["effective_verify_workers"],2)
        self.assertEqual(resources.LOW.ready()["commit_wait_ms"],100)
        self.assertEqual(resources.LOW.process_memory_bytes,512*resources.MiB)
        with patch.dict(os.environ,{"GOMAXPROCS":"256","GOMEMLIMIT":"1TiB","GG_NATIVE_RESOURCES":"SERVER"}):
            environment=native._environment()
            self.assertEqual(environment["GOMAXPROCS"],"2")
            self.assertEqual(environment["GOMEMLIMIT"],"256MiB")
            self.assertNotIn("GG_NATIVE_RESOURCES",environment)
        self.assertEqual(resources.resolve(resources.LOW.wire()),resources.LOW)
        self.assertEqual(resources.resolve({"schema":resources.SCHEMA,"mode":"LOW"}),resources.LOW)

    def test_server_is_finite_strict_numeric_and_supports_explicit_256_without_host_detection(self):
        maximum=server(go_max_procs=256,verify_workers=256)
        self.assertEqual(resources.resolve(maximum.wire()),maximum)
        self.assertEqual(maximum.ready()["effective_verify_workers"],256)
        self.assertEqual(maximum.ready()["commit_wait_ms"],10)
        self.assertEqual(maximum.environment(),{"GOMAXPROCS":"256","GOMEMLIMIT":"268435456B"})
        for name in resources.NativeResources.__dataclass_fields__:
            if name=="mode":continue
            for invalid in (True,"2",2.0,None):
                with self.subTest(name=name,invalid=invalid),self.assertRaises(ValueError):
                    server(**{name:invalid})
        for change in ({"mode":"AUTO"},{"go_max_procs":0},{"go_max_procs":257},
                {"verify_workers":33},{"verify_workers":0},{"go_heap_bytes":512*resources.MiB},
                {"process_memory_bytes":511*resources.MiB},{"owner_memory_bytes":0},
                {"virtual_bytes":4*resources.GiB},{"open_files":65537},{"owner_cpu_basis_points":10001},
                {"maximum_native_children":7},{"go_heap_bytes":256*resources.MiB+1}):
            with self.subTest(change=change),self.assertRaises(ValueError):server(**change)
        for bad in ({"schema":resources.SCHEMA,"mode":"SERVER"},dict(maximum.wire(),unknown=1),
                dict(resources.LOW.wire(),go_max_procs=3),dict(maximum.wire(),schema="future")):
            with self.subTest(bad=bad),self.assertRaises(ValueError):resources.resolve(bad)

    def test_settings_are_local_copied_and_legacy_low_shape_is_unchanged(self):
        legacy=settings()
        self.assertEqual(protocol.validate_settings(legacy),legacy)
        self.assertEqual(protocol.validate_settings(dict(legacy,resources=resources.LOW.wire())),legacy)
        selected=server();original=dict(legacy,resources=selected.wire())
        normalized=protocol.validate_settings(original)
        original["resources"]["verify_workers"]=1
        self.assertEqual(normalized["resources"],selected.wire())
        for key,value in (("role","VALIDATOR"),("resources",{"schema":resources.SCHEMA,"mode":"LIGHT"})):
            with self.subTest(key=key),self.assertRaises(ValueError):
                protocol.validate_settings(dict(legacy,**{key:value}))

    def test_attempt_freezes_one_profile_and_any_mutation_fails_closed(self):
        selected=server();node=SimpleNamespace(settings=dict(settings(),resources=selected.wire()))
        captured=resources.capture(node)
        self.assertIs(resources.current(node),captured)
        with self.assertRaises(FrozenInstanceError):captured.go_max_procs=256
        self.assertEqual(resources.bootstrap(node,{"schema":"public"})["resources"],selected.wire())
        node.settings["resources"]=resources.LOW.wire()
        self.assertFalse(resources.matches(node))
        for action in (lambda:resources.current(node),lambda:resources.bootstrap(node,{}),
                lambda:resources.readiness(node,{})):
            with self.assertRaisesRegex(ValueError,"PROFILE_CHANGED"):action()

    def test_new_owned_low_readiness_requires_actual_attestation_not_a_missing_or_different_frame(self):
        # _read_ready is the real bounded pipe decoder; no successful process
        # launch is inferred from this framing seam.
        node=SimpleNamespace();resources.capture(node)
        expected=resources.readiness(node,{"schema":"public","pid":123,"rpc_port":23450,"p2p_port":23451})
        for mutation in ("missing","cpu","workers","heap","commit","profile"):
            actual=deepcopy(expected)
            if mutation=="missing":actual.pop("resources")
            elif mutation=="profile":actual["resources"]["profile"]=server().wire()
            else:
                field={"cpu":"go_max_procs","workers":"effective_verify_workers",
                    "heap":"go_heap_bytes","commit":"commit_wait_ms"}[mutation]
                actual["resources"][field]+=1
            process=SimpleNamespace(stdout=io.BytesIO(native._pack(actual)+b"\n"))
            record={"process":process,"_ready":None}
            native._read_ready(record,process,expected)
            self.assertIsNone(record["_ready"],mutation)
        process=SimpleNamespace(stdout=io.BytesIO(native._pack(expected)+b"\n"))
        record={"process":process,"_ready":None};native._read_ready(record,process,expected)
        self.assertIs(record["_ready"]["process"],process)
        self.assertEqual(record["_ready"]["resources"],resources.LOW.ready())
        one=server(go_max_procs=1,verify_workers=1,maximum_native_children=1).ready()
        self.assertTrue(resources.valid_readiness(one))
        for target,key in ((one,"go_max_procs"),(one["profile"],"maximum_native_children")):
            saved=target[key];target[key]=True
            self.assertFalse(resources.valid_readiness(one))
            target[key]=saved

    def test_public_status_never_labels_requested_profile_as_applied_without_same_child_ack(self):
        selected=server();process=SimpleNamespace(poll=lambda:None)
        node=SimpleNamespace(settings=dict(settings(),resources=selected.wire()),
            _node={"process":process,"_ready":None},_lease=None)
        resources.capture(node)
        initial=resources.observation(node)
        self.assertEqual(initial["state"],"AWAITING_NATIVE_ACK")
        self.assertEqual(initial["requested"],selected.wire());self.assertIsNone(initial["applied"])
        node._node["_ready"]={"process":SimpleNamespace(),"resources":selected.ready()}
        self.assertIsNone(resources.observation(node)["applied"])
        node._node["_ready"]={"process":process,"resources":selected.ready(),"sdk_rates":selected.sdk_rates()}
        node._lease=SimpleNamespace(facts={"provider":"PUBLIC_KERNEL_TEST_SEAM","verified":True,
            "memory_bytes":512*resources.MiB,"private_path":"must never be exposed"})
        active=resources.observation(node)
        self.assertEqual(active["state"],"APPLIED");self.assertEqual(active["applied"],selected.ready())
        self.assertNotIn("private_path",active["kernel"])
        self.assertEqual(active["applied_sdk_rates"],selected.sdk_rates())
        node._node["_ready"].pop("sdk_rates")
        self.assertIsNone(resources.observation(node)["applied"])
        node._node["_ready"]["sdk_rates"]=selected.sdk_rates()
        node.settings["resources"]=resources.LOW.wire()
        changed=resources.observation(node)
        self.assertEqual(changed["state"],"PROFILE_CHANGED");self.assertIsNone(changed["applied"])
        node.settings["resources"]=selected.wire();process.poll=lambda:0
        self.assertIsNone(resources.observation(node)["applied"])
        from backend.terminal_cli import foreground_summary
        public=foreground_summary("protocol.node_start",{"protocol_network":{"resources":initial}})
        self.assertEqual(public["resources"],initial);self.assertIsNone(public["resources"]["applied"])

    def test_light_status_compares_requested_profile_owner_and_process_epoch_to_captured_transport(self):
        from backend.gg_protocol_light import LightProtocolNode
        selected=server();owner,profile=object(),object();process=SimpleNamespace(poll=lambda:None)
        pipe=SimpleNamespace(_resources=selected,ready={"resources":selected.ready(),
            "local_limits":selected.transport(),"limits":selected.transport()},
            _lease=SimpleNamespace(facts={"verified":True}),alive=lambda:True,
            _protected_owners=(owner,profile),process=process)
        node=LightProtocolNode.__new__(LightProtocolNode)
        node.settings=dict(settings(),resources=selected.wire());node.owner=owner;node.profile=profile
        node._transport=pipe;node._node={"process":process};node._owner_stopped=lambda:False
        native=LightProtocolNode.resource_observation(node)
        self.assertEqual(native["state"],"APPLIED");self.assertEqual(native["applied"],selected.ready())
        node.settings["resources"]=resources.LOW.wire()
        changed=LightProtocolNode.resource_observation(node)
        self.assertEqual(changed["state"],"PROFILE_CHANGED")
        self.assertEqual(changed["requested"],resources.LOW.wire())
        self.assertEqual(changed["captured"],selected.wire());self.assertIsNone(changed["applied"])
        node.settings["resources"]=selected.wire();node.owner=object()
        self.assertIsNone(LightProtocolNode.resource_observation(node)["applied"])
        node.owner=owner;node._node={"process":SimpleNamespace()}
        self.assertIsNone(LightProtocolNode.resource_observation(node)["applied"])

    def test_codec_merge_hook_requires_native_ack_and_never_resets_any_governor(self):
        selected=server()
        observed={"native_attested":False,"applied":None}
        node=SimpleNamespace(settings=dict(settings(),resources=selected.wire()),
            resource_observation=lambda:deepcopy(observed))
        resources.capture(node)
        with self.assertRaisesRegex(ValueError,"ACK_REQUIRED"):resources.codec_limits(node)
        observed.update(state="APPLIED",native_attested=True,applied=selected.ready())
        first=resources.codec_limits(node)
        self.assertEqual(first["work_burst"],256)
        self.assertEqual(first["workspaces"],32)
        self.assertEqual(first["byte_burst"],256*(32768+4*((32768+2)//3)+2048))
        self.assertEqual(resources.codec_limits(node),first)
        observed["authenticated_peer_receive_limits"]=resources.LOW.transport()
        self.assertEqual(resources.codec_limits(node)["work_burst"],8)
        node=SimpleNamespace(resource_observation=lambda:{"state":"APPLIED","native_attested":True,"applied":resources.LOW.ready()})
        low=resources.codec_limits(node)
        self.assertEqual(low["work_burst"],8);self.assertEqual(low["workspaces"],2)

    def test_sdk_rates_preserve_low_scale_to256_and_require_exact_ready_facts(self):
        self.assertEqual(resources.LOW.sdk_rates(),{"sdk_send_bytes_per_second":5120000,"sdk_recv_bytes_per_second":5120000})
        selected=server(go_max_procs=256,verify_workers=256)
        self.assertEqual(selected.sdk_rates(),{"sdk_send_bytes_per_second":17179869184,"sdk_recv_bytes_per_second":17179869184})
        for invalid in (0,257,2**100,True,256.0):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):server(go_max_procs=invalid,verify_workers=1)
        node=SimpleNamespace(settings=dict(settings(),resources=selected.wire()))
        resources.capture(node)
        expected=resources.readiness(node,{"pid":123,"rpc_port":23450,"p2p_port":23451})
        for name in ("sdk_send_bytes_per_second","sdk_recv_bytes_per_second"):
            for wrong in (None,True,5120000,17179869185,17179869184.0):
                actual=deepcopy(expected)
                if wrong is None:actual.pop(name)
                else:actual[name]=wrong
                process=SimpleNamespace(stdout=io.BytesIO(native._pack(actual)+b"\n"))
                record={"process":process,"_ready":None}
                native._read_ready(record,process,expected)
                self.assertIsNone(record["_ready"],(name,wrong))
        process=SimpleNamespace(stdout=io.BytesIO(native._pack(expected)+b"\n"))
        record={"process":process,"_ready":None};native._read_ready(record,process,expected)
        self.assertEqual(record["_ready"]["sdk_rates"],selected.sdk_rates())

    def test_owned_restore_ready_requires_exact_integer_sdk_facts_before_publication(self):
        from backend import gg_protected_restore as restore
        process=SimpleNamespace(pid=123)
        for selected in (resources.LOW,server(go_max_procs=256,verify_workers=256)):
            node=SimpleNamespace(settings={"resources":selected.wire()},
                _native_ready=lambda process:{"pid":process.pid,"rpc_port":23450,"p2p_port":23451})
            resources.capture(node)
            expected=resources.readiness(node,node._native_ready(process))
            record=restore._validated_ready_frame(node,process,expected)
            self.assertEqual(record["sdk_rates"],selected.sdk_rates())
            for name in selected.sdk_rates():
                for wrong in (float(expected[name]),True,str(expected[name]),None):
                    bad=deepcopy(expected);bad[name]=wrong
                    with self.subTest(mode=selected.mode,field=name,wrong=wrong),self.assertRaisesRegex(ValueError,"RESTORE_READY"):
                        restore._validated_ready_frame(node,process,bad)
            self.assertFalse(resources.valid_sdk_rates(selected,{**selected.sdk_rates(),"extra":1}))

    def test_sdk_ready_maximum_profile_fits_original_frame_and_transport_does_not_claim_sdk_rates(self):
        selected=server(go_max_procs=256,verify_workers=256,go_heap_bytes=2**40-64*resources.MiB,
            process_memory_bytes=2**40,virtual_bytes=2**44,open_files=65536,owner_memory_bytes=2**42)
        expected={"schema":"gg.consensus.protocol-ready.v1","chain_id":"ggnet:"+"a"*24,
            "genesis_hash":"b"*64,"node_id":"c"*40,"pid":2**63-1,"rpc_port":65535,"p2p_port":65534,
            "p2p_host":"ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff","role":"VALIDATOR",
            "consensus_signing":False,"state_sync":False,"resources":selected.ready(),**selected.sdk_rates()}
        self.assertEqual(len(native._pack(expected)),967)
        self.assertLessEqual(len(native._pack(expected))+1,1024)
        pipe=SimpleNamespace(_resources=selected,ready={"resources":selected.ready(),
            "local_limits":selected.transport(),"limits":selected.transport()},
            _lease=SimpleNamespace(facts={"verified":True}),alive=lambda:True)
        status=resources.pipe_observation(pipe)
        self.assertEqual(status["state"],"APPLIED")
        self.assertFalse(status["full_sdk_node_running"])
        self.assertNotIn("applied_sdk_rates",status)
        self.assertNotIn("requested_sdk_rates",status)

    def test_server_posix_policy_uses_finite_public_argv_and_preserves_mode_whitelist(self):
        selected=server()
        with patch.object(posix,"supported",return_value=True),patch.object(posix.subprocess,"Popen") as spawn:
            for arguments in ((),("financial-owned-restore-start",)):
                posix.launch("/public/sdk",cwd="/public",env={},arguments=arguments,resources=selected)
                argv=spawn.call_args.args[0]
                self.assertEqual(argv[-1],"--gg-server-limits=536870912,8589934592,1024")
                self.assertEqual(argv[-2],arguments[0] if arguments else "/public/sdk")
                self.assertTrue(spawn.call_args.kwargs["start_new_session"])
            for arguments in (("--gg-server-limits=1,2,3",),("financial-owned-restore-start","extra")):
                with self.assertRaisesRegex(ValueError,"LAUNCH_ARGUMENTS"):
                    posix.launch("/public/sdk",cwd="/public",env={},arguments=arguments,resources=selected)
        self.assertEqual(posix._server_argument("--gg-server-limits=536870912,8589934592,1024"),
            (512*resources.MiB,8*resources.GiB,1024))
        for value in ("--gg-server-limits=0536870912,8589934592,1024",
                "--gg-server-limits=536870912,8589934592,unlimited",
                "--gg-server-limits=536870912,8589934592,1024,1",
                "--gg-server-limits=536870912,8589934592,65537"):
            with self.subTest(value=value),self.assertRaises(ValueError):posix._server_argument(value)


if __name__=="__main__":unittest.main()
