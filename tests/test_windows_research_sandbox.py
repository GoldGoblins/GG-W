"""Actual Windows AppContainer boundaries for RESEARCH's trusted tools."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from backend import windows_research_sandbox as sandbox


@unittest.skipUnless(os.name == 'nt' and shutil.which('node'), 'Native Windows and Node required')
class WindowsResearchSandboxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gg-research-ac-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.tools = self.root / 'tools'
        self.scratch = self.root / 'scratch'
        (self.tools / 'runtime').mkdir(parents=True)
        self.scratch.mkdir()
        self.node = self.tools / 'runtime/node.exe'
        shutil.copyfile(shutil.which('node'), self.node)

    def execute(self, script, *, timeout=5, limit=32768, cancelled=None):
        return sandbox.run([str(self.node), '-e', script], scratch=self.scratch,
                           tools=self.tools, timeout=timeout, max_output_bytes=limit,
                           cancelled=cancelled)

    def test_actual_files_environment_and_network_are_isolated(self):
        private = self.root / 'private-fixture.txt'
        private.write_text('Synthetic fixture, not a credential', encoding='utf-8')
        selected = self.scratch / 'target.js'
        selected.write_text('export const fixture = 7;', encoding='utf-8')
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(.2)
        # Positive control: this listener is reachable outside the sandbox.
        with socket.create_connection(listener.getsockname(), timeout=1):
            accepted, _ = listener.accept()
            accepted.close()
        script = """
const fs = require('node:fs'), path = require('node:path'), net = require('node:net');
const result = {privateVisible:fs.existsSync(__PRIVATE__), selectedReadable:false,
    selectedImmutable:false, toolsImmutable:false, profileImmutable:false,
    inheritedEnv:Boolean(process.env.GG_SANDBOX_TEST_PRIVATE)};
result.selectedReadable = fs.readFileSync(__SELECTED__,'utf8').includes('fixture');
try { fs.writeFileSync(__SELECTED__,'changed'); } catch(error) { result.selectedImmutable=true; }
try { fs.writeFileSync(__TOOLS_OUT__,'changed'); } catch(error) { result.toolsImmutable=true; }
try { fs.writeFileSync(__PROFILE_OUT__,'changed'); } catch(error) { result.profileImmutable=true; }
fs.writeFileSync(path.join(process.env.HOME,'own.txt'),'allowed');
fs.writeFileSync(path.join(process.env.TEMP,'own.txt'),'allowed');
const connection=net.connect({host:'127.0.0.1',port:__PORT__});
connection.on('connect',()=>{result.network='CONNECTED';connection.destroy();});
connection.on('error',(error)=>{result.network=error.code;});
setTimeout(()=>{connection.destroy();console.log(JSON.stringify(result));},350);
"""
        for name, value in [('PRIVATE', str(private)), ('SELECTED', str(selected)),
                            ('TOOLS_OUT', str(self.tools / 'unwanted.txt')),
                            ('PROFILE_OUT', str(Path(os.environ['LOCALAPPDATA']) / 'Packages'
                                / ('GoldGoblins.Research.' + hashlib.sha256(str(self.tools.resolve()).casefold().encode()).hexdigest()[:16]).lower()
                                / 'AC/unwanted.txt'))]:
            script = script.replace('__' + name + '__', json.dumps(value))
        script = script.replace('__PORT__', str(listener.getsockname()[1]))
        with patch.dict(os.environ, {'GG_SANDBOX_TEST_PRIVATE': 'synthetic fixture'}):
            code, output, errors, trigger = self.execute(script)
        self.assertEqual(trigger, 'NONE', errors.decode('utf-8', 'replace'))
        self.assertEqual(code, 0, errors.decode('utf-8', 'replace'))
        result = json.loads(output)
        self.assertEqual({key: result[key] for key in ('privateVisible', 'selectedReadable', 'selectedImmutable', 'toolsImmutable', 'profileImmutable', 'inheritedEnv')},
                         {'privateVisible': False, 'selectedReadable': True, 'selectedImmutable': True,
                          'toolsImmutable': True, 'profileImmutable': True, 'inheritedEnv': False})
        self.assertIn(result['network'], ('EACCES', 'EPERM', 'ETIMEDOUT', 'ENETUNREACH'))
        with self.assertRaises(socket.timeout):
            listener.accept()
        self.assertTrue((self.scratch / 'home/own.txt').is_file())
        self.assertEqual(len(list((self.scratch / 'tmp').rglob('own.txt'))), 1)
        self.assertFalse((self.tools / 'unwanted.txt').exists())
        self.assertIn('fixture', selected.read_text(encoding='utf-8'))

    def test_real_module_entry_and_relative_import_work_without_ancestor_access(self):
        (self.tools / 'package').mkdir()
        (self.tools / 'package/helper.mjs').write_text('export const fixture = 42;', encoding='utf-8')
        entry = self.tools / 'package/entry.mjs'
        entry.write_text("import {fixture} from './helper.mjs'; console.log(JSON.stringify({fixture}));", encoding='utf-8')
        code, output, errors, trigger = sandbox.run([
            str(self.node), '--preserve-symlinks', '--preserve-symlinks-main', str(entry)],
            scratch=self.scratch, tools=self.tools, timeout=5, max_output_bytes=8192)
        self.assertEqual((code, trigger), (0, 'NONE'), errors.decode('utf-8', 'replace'))
        self.assertEqual(json.loads(output), {'fixture': 42})

    def test_cancellation_kills_a_started_descendant(self):
        child = "setTimeout(()=>require('node:fs').writeFileSync(process.env.HOME+'/survived.txt','bad'),900)"
        script = "const fs=require('node:fs');const child=require('node:child_process').spawn(process.execPath,['-e'," + json.dumps(child) + "],{windowsHide:true,stdio:'ignore'});"
        script += "child.on('spawn',()=>fs.writeFileSync(process.env.HOME+'/ready.txt','yes'));setInterval(()=>{},1000);"
        _, _, _, trigger = self.execute(script,
            cancelled=lambda: (self.scratch / 'home/ready.txt').exists())
        self.assertEqual(trigger, 'CANCELLED')
        self.assertTrue((self.scratch / 'home/ready.txt').exists())
        time.sleep(1.1)
        self.assertFalse((self.scratch / 'home/survived.txt').exists())

    def test_output_limit_and_timeout_are_bounded(self):
        code, output, errors, trigger = self.execute("process.stdout.write('x'.repeat(1000000));setTimeout(()=>{},30000)", limit=4096)
        self.assertEqual(trigger, 'OUTPUT_LIMIT')
        self.assertLessEqual(len(output) + len(errors), 4096)
        began = time.monotonic()
        _, _, _, trigger = self.execute('setInterval(()=>{},1000)', timeout=.2)
        self.assertEqual(trigger, 'TIMEOUT')
        self.assertLess(time.monotonic() - began, 10)

    def test_cancellation_and_callback_exception_terminate_children(self):
        _, _, _, trigger = self.execute('setInterval(()=>{},1000)', cancelled=lambda: True)
        self.assertEqual(trigger, 'CANCELLED')

        def failed_budget():
            raise ValueError('SCRATCH_LIMIT')

        with self.assertRaisesRegex(ValueError, 'SCRATCH_LIMIT'):
            self.execute('setInterval(()=>{},1000)', cancelled=failed_budget)

    def test_executable_outside_tools_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SANDBOX_SCOPE_INVALID'):
            sandbox.run([shutil.which('node'), '-e', 'process.exit(0)'], scratch=self.scratch,
                        tools=self.tools, timeout=1, max_output_bytes=1000)

    def test_home_and_source_roots_cannot_be_granted_to_a_tool(self):
        with patch.object(sandbox, '_run_native', side_effect=AssertionError('Unsafe scope reached native launch')):
            for root in (Path.home(), PROJECT, PROJECT.parent):
                with self.subTest(root=root), self.assertRaisesRegex(ValueError, 'SANDBOX_SCOPE_INVALID'):
                    sandbox.run([str(self.node), '-e', 'process.exit(0)'], scratch=self.scratch,
                                tools=root, timeout=1, max_output_bytes=1000)

    def test_installed_jdk_loads_security_configuration_and_classpath_jar(self):
        from backend.research_lab import TOOLS_ROOT
        tools = TOOLS_ROOT.resolve()
        compiler = tools / 'jdk/bin/javac.exe'
        library = tools / 'ghidra/Ghidra/Framework/Utility/lib/Utility.jar'
        if not compiler.is_file() or not library.is_file():
            self.skipTest('Installed research JDK and Ghidra required')
        with tempfile.TemporaryDirectory(prefix='.ac-java-test-', dir=tools) as raw:
            fixture = Path(raw)
            source = fixture / 'GGSecurityProbe.java'
            source.write_text('''import java.nio.file.*;
import java.util.jar.*;
public class GGSecurityProbe {
    public static void main(String[] args) throws Exception {
        Path configuration = Path.of(System.getProperty("java.home"), "conf", "security", "java.security");
        if (Files.readAllBytes(configuration).length == 0) throw new AssertionError("Empty configuration");
        configuration.toRealPath();
        if (java.security.Security.getProviders().length == 0) throw new AssertionError("Missing providers");
        java.security.MessageDigest.getInstance("SHA-256").digest(new byte[]{7});
        try (JarFile jar = new JarFile(args[0])) {
            if (jar.size() == 0) throw new AssertionError("Empty classpath jar");
        }
        java.io.File directory = new java.io.File(System.getProperty("user.home"), "osgi/data");
        if (!directory.mkdirs() && !directory.isDirectory()) throw new AssertionError("Scratch directory missing");
        java.io.File child = new java.io.File(directory, "cache.dat");
        String canonicalDirectory = directory.getCanonicalPath() + java.io.File.separator;
        if (!child.getCanonicalPath().startsWith(canonicalDirectory)) throw new AssertionError("Nonexistent cache path escaped data directory");
        Files.writeString(child.toPath(), "fixture");
        if (!child.getCanonicalPath().startsWith(canonicalDirectory)) throw new AssertionError("Existing cache path escaped data directory");
        java.io.File legacyTemporary = java.io.File.createTempFile("gg-fixture-", ".tmp");
        Path nioTemporary = Files.createTempFile("gg-fixture-", ".tmp");
        if (!legacyTemporary.isFile() || !Files.isRegularFile(nioTemporary)) throw new AssertionError("Java temp creation failed");
        Files.delete(legacyTemporary.toPath());
        Files.delete(nioTemporary);
        boolean denied = false;
        try { java.io.File.createTempFile("gg-denied-", ".tmp", new java.io.File(args[1])); }
        catch (java.io.IOException expected) { denied = true; }
        if (!denied) throw new AssertionError("Host file creation was permitted");
        Path hostFile = Path.of(args[1], "private.txt");
        denied = false;
        try { Files.readAllBytes(hostFile); } catch (java.io.IOException expected) { denied = true; }
        if (!denied) throw new AssertionError("Host file read was permitted");
        denied = false;
        try { hostFile.toRealPath(); } catch (java.io.IOException expected) { denied = true; }
        if (!denied) throw new AssertionError("Private host path canonicalization was permitted");
        System.out.println("JAVA_SECURITY_AND_JAR=PASS");
    }
}''', encoding='utf-8')
            compiled = subprocess.run([str(compiler), str(source)], capture_output=True,
                                      timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(compiled.returncode, 0, compiled.stderr.decode('utf-8', 'replace'))
            private_directory = self.root / 'host-private'
            private_directory.mkdir()
            (private_directory / 'private.txt').write_text('Synthetic fixture only', encoding='utf-8')
            code, output, errors, trigger = sandbox.run([
                str(tools / 'jdk/bin/java.exe'), '-cp', str(fixture), 'GGSecurityProbe', str(library), str(private_directory)],
                scratch=self.scratch, tools=tools, timeout=10, max_output_bytes=8192)
            self.assertEqual((code, trigger), (0, 'NONE'), errors.decode('utf-8', 'replace'))
            self.assertIn(b'JAVA_SECURITY_AND_JAR=PASS', output)
            self.assertEqual([path.name for path in private_directory.iterdir()], ['private.txt'])


if __name__ == '__main__':
    unittest.main()
