"""The phone app's build chain and APK check (SECURITY.md 88, 96, 97, 99). No Gradle runs here:
these read the config files and feed check-apk.py the text aapt2 prints.
Run: python3 -m unittest discover -s tests -v"""
import re
import unittest
from pathlib import Path

from test_julz_notify import load

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "android"
check = load("check_apk", "android/check-apk.py")

A = "http://schemas.android.com/apk/res/android"
XML = f'''N: android={A} (line=2)
  E: manifest (line=2)
    E: application (line=10)
      E: activity (line=32)
        A: {A}:name(0x01010003)="app.julz.MainActivity" (Raw: "app.julz.MainActivity")
        A: {A}:exported(0x01010010)=false
      E: activity-alias (line=40)
        A: {A}:name(0x01010003)="app.julz.IconMagenta" (Raw: ".IconMagenta")
        A: {A}:enabled(0x0101000e)=true
        A: {A}:exported(0x01010010)=true
        A: {A}:targetActivity(0x01010202)="app.julz.MainActivity" (Raw: ".MainActivity")
        E: intent-filter (line=45)
          E: action (line=46)
            A: {A}:name(0x01010003)="android.intent.action.MAIN" (Raw: "android.intent.action.MAIN")
      E: activity-alias (line=50)
        A: {A}:name(0x01010003)="app.julz.IconCyan" (Raw: ".IconCyan")
        A: {A}:enabled(0x0101000e)=false
        A: {A}:exported(0x01010010)=true
        A: {A}:targetActivity(0x01010202)="app.julz.MainActivity" (Raw: ".MainActivity")
      E: provider (line=49)
        A: {A}:name(0x01010003)="androidx.startup.InitializationProvider" (Raw: "x")
        A: {A}:exported(0x01010010)=false
      E: service (line=55)
        A: {A}:name(0x01010003)=".FeedService" (Raw: ".FeedService")
'''
RECEIVER = f'''      E: receiver (line=64)
        A: {A}:name(0x01010003)="androidx.profileinstaller.ProfileInstallReceiver" (Raw: "x")
        A: {A}:permission(0x01010006)="android.permission.DUMP" (Raw: "x")
        A: {A}:exported(0x01010010)=true
'''
PERMS = ("package: app.julz\npermission: app.julz.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION\n"
         "uses-permission: name='app.julz.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION'\n")


class CheckApkTest(unittest.TestCase):
    def test_the_skeleton_passes(self):
        self.assertEqual(check.check(PERMS, XML), [])

    def test_main_activity_exported_again_is_caught(self):
        # since 135 the launcher is the aliases; MainActivity itself is not exported
        xml = XML.replace('"app.julz.MainActivity")\n        A: ' + A + ':exported(0x01010010)=false',
                          '"app.julz.MainActivity")\n        A: ' + A + ':exported(0x01010010)=true')
        self.assertIn("app.julz.MainActivity", " ".join(check.check(PERMS, xml)))

    def test_an_alias_of_another_activity_is_caught(self):
        xml = XML.replace('targetActivity(0x01010202)="app.julz.MainActivity" (Raw: ".MainActivity")\n'
                          '        E: intent-filter',
                          'targetActivity(0x01010202)="app.julz.SecretActivity" (Raw: ".SecretActivity")\n'
                          '        E: intent-filter')
        problems = check.check(PERMS, xml)
        self.assertEqual(len(problems), 1)
        self.assertIn("SecretActivity", problems[0])

    def test_an_alias_off_the_list_is_caught(self):
        xml = XML.replace('"app.julz.IconCyan" (Raw: ".IconCyan")', '"app.julz.IconPink" (Raw: ".IconPink")')
        self.assertIn("app.julz.IconPink", " ".join(check.check(PERMS, xml)))

    def test_every_accent_has_its_alias_on_the_list(self):
        self.assertEqual(len(check.EXPORTED_OK), 7)
        self.assertNotIn("app.julz.MainActivity", check.EXPORTED_OK)

    def test_a_library_receiver_exported_is_caught(self):
        problems = check.check(PERMS, XML + RECEIVER)
        self.assertEqual(len(problems), 1)
        self.assertIn("ProfileInstallReceiver", problems[0])

    def test_an_exported_service_of_ours_is_caught(self):
        xml = XML.replace('".FeedService")\n', '".FeedService")\n        A: ' + A
                          + ':exported(0x01010010)=true\n')
        self.assertIn("app.julz.FeedService", " ".join(check.check(PERMS, xml)))

    def test_a_new_permission_is_caught(self):
        problems = check.check(PERMS + "uses-permission: name='android.permission.READ_CONTACTS'\n", XML)
        self.assertIn("READ_CONTACTS", " ".join(problems))

    def test_exported_flag_on_a_child_element_does_not_count_for_its_parent(self):
        xml = XML.replace('A: ' + A + ':exported(0x01010010)=false\n',
                          'E: meta-data (line=50)\n          A: ' + A + ':exported(0x01010010)=true\n')
        self.assertEqual(check.check(PERMS, xml), [])


    def test_a_debuggable_build_is_refused_unless_asked_for(self):
        # threat 89: debug builds skip FLAG_SECURE, so a release must never be debuggable
        for value in ("true", "0xffffffff"):
            xml = XML.replace("    E: application (line=10)\n", "    E: application (line=10)\n"
                              f"      A: {A}:debuggable(0x0101000f)={value}\n")
            self.assertIn("debuggable", " ".join(check.check(PERMS, xml)))
            self.assertEqual(check.check(PERMS, xml, debug_ok=True), [])
        off = XML.replace("    E: application (line=10)\n", "    E: application (line=10)\n"
                          f"      A: {A}:debuggable(0x0101000f)=false\n")
        self.assertEqual(check.check(PERMS, off), [])

    def test_install_never_passes_debug(self):
        self.assertNotIn("--debug", (APP / "install.py").read_text())

    def test_a_component_ends_at_the_next_element_on_its_level(self):
        # attributes of an application level sibling never count for the service before it
        xml = XML + '      E: meta-data (line=60)\n        A: ' + A + ':exported(0x01010010)=true\n'
        self.assertEqual(check.check(PERMS, xml), [])


devtools = load("devtools", "android/devtools.py")
UNIX = """Num       RefCount Protocol Flags    Type St Inode Path
0000000000000000: 00000002 00000000 00010000 0001 01 245612173 @webview_devtools_remote_6550
0000000000000000: 00000002 00000000 00010000 0001 01 243403370 @stetho_com.google.android.apps.messaging:rcs_devtools_remote
0000000000000000: 00000002 00000000 00010000 0001 01 243403371 @webview_devtools_remote_777
0000000000000000: 00000002 00000000 00010000 0001 01 243403372 @chrome_devtools_remote
"""


class DevtoolsTest(unittest.TestCase):
    """Threat 105: only the app's own inspection socket, forwarded for one command."""

    def test_only_the_apps_own_socket(self):
        self.assertEqual(devtools.devtools_socket(UNIX, "6550"), "webview_devtools_remote_6550")
        self.assertEqual(devtools.devtools_socket(UNIX, "777"), "webview_devtools_remote_777")
        for pid in ("655", "65500", "1", ""):
            self.assertIsNone(devtools.devtools_socket(UNIX, pid), pid)
        self.assertIsNone(devtools.devtools_socket("x @webview_devtools_remote_6550_evil\n", "6550"))

    def test_the_forward_is_removed_even_when_the_command_fails(self):
        from unittest import mock
        calls = []

        def fake_adb(*args):
            calls.append(args)
            return {"pidof": "6550\n", "cat": UNIX}.get(args[1] if len(args) > 1 else "", "")

        with mock.patch.object(devtools, "adb", fake_adb), \
                mock.patch.object(devtools, "connect", side_effect=ConnectionError("x")):
            with self.assertRaises(ConnectionError):
                devtools.main(["last"])
        forward = [c for c in calls if c[0] == "forward"]
        self.assertEqual(len(forward), 2)
        port = forward[0][1]
        self.assertEqual(forward[0], ("forward", port, "localabstract:webview_devtools_remote_6550"))
        self.assertEqual(forward[1], ("forward", "--remove", port))
        self.assertTrue(port.startswith("tcp:"))

    def test_no_socket_no_forward(self):
        from unittest import mock
        calls = []

        def fake_adb(*args):
            calls.append(args)
            return {"pidof": "6550\n", "cat": "nothing here\n"}.get(args[1] if len(args) > 1 else "", "")

        with mock.patch.object(devtools, "adb", fake_adb):
            self.assertEqual(devtools.main(["last"]), 1)
        self.assertFalse([c for c in calls if c[0] == "forward"])


install = load("install_apk", "android/install.py")
PIN = "a" * 64
SIGNED = ("Verifies\nVerified using v1 scheme (JAR signing): false\n"
          "Verified using v2 scheme (APK Signature Scheme v2): true\n"
          "Verified using v3 scheme (APK Signature Scheme v3): true\n"
          "Number of signers: 1\nSigner #1 certificate DN: CN=Julz\n"
          f"Signer #1 certificate SHA-256 digest: {PIN}\n")


class InstallTest(unittest.TestCase):
    """Threat 96: only an APK signed by the pinned release key goes on the phone."""

    def test_the_pinned_key_passes(self):
        self.assertEqual(install.check_signature(SIGNED, PIN), [])

    def test_another_key_is_refused(self):
        self.assertIn("another key", " ".join(install.check_signature(SIGNED, "b" * 64)))

    def test_two_signers_are_refused(self):
        two = SIGNED.replace("Number of signers: 1", "Number of signers: 2") + \
            "Signer #2 certificate SHA-256 digest: " + "b" * 64 + "\n"
        self.assertTrue(install.check_signature(two, PIN))

    def test_a_signature_that_does_not_verify_is_refused(self):
        self.assertTrue(install.check_signature(SIGNED.replace("Verifies", "DOES NOT VERIFY"), PIN))
        self.assertTrue(install.check_signature("", PIN))

    def test_no_signer_line_is_refused_not_a_crash(self):
        no_digest = "\n".join(l for l in SIGNED.splitlines() if "SHA-256 digest" not in l)
        self.assertIn("exactly one signer", " ".join(install.check_signature(no_digest, PIN)))

    def test_v1_only_is_refused(self):
        v1 = SIGNED.replace("v2): true", "v2): false").replace("v3): true", "v3): false") \
            .replace("(JAR signing): false", "(JAR signing): true")
        self.assertIn("v2 or v3", " ".join(install.check_signature(v1, PIN)))

class BuildChainTest(unittest.TestCase):
    def test_gradle_is_pinned_by_hash(self):
        props = (APP / "gradle" / "wrapper" / "gradle-wrapper.properties").read_text()
        self.assertRegex(props, r"distributionSha256Sum=[0-9a-f]{64}")
        self.assertIn("distributionUrl=https\\://services.gradle.org/", props)

    def test_every_dependency_is_hash_checked(self):
        meta = (APP / "gradle" / "verification-metadata.xml").read_text()
        self.assertIn("<verify-metadata>true</verify-metadata>", meta)
        self.assertGreater(meta.count("<sha256 value="), 100)
        self.assertNotIn("<trusted-artifacts>", meta)  # no blanket exceptions

    def test_only_google_and_maven_central(self):
        settings = (APP / "settings.gradle.kts").read_text()
        self.assertIn("RepositoriesMode.FAIL_ON_PROJECT_REPOS", settings)
        repos = set(re.findall(r"^\s+(\w+)\(\)$", settings, re.M))
        self.assertEqual(repos, {"google", "mavenCentral", "gradlePluginPortal"})

    def test_no_firebase_play_or_analytics(self):
        text = (APP / "app" / "build.gradle.kts").read_text()
        deps = "\n".join(l.split("//")[0] for l in text.splitlines())  # settings, not comments
        for bad in ("firebase", "play-services", "gms", "analytics", "crashlytics"):
            self.assertNotIn(bad, deps.lower(), bad)

    def test_manifest_basics(self):
        manifest = (APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text()
        self.assertIn('android:allowBackup="false"', manifest)  # threat 88
        # threats 99, 135: exported only the launcher aliases, each of MainActivity, one per accent
        self.assertEqual(manifest.count('android:exported="true"'), len(check.ICONS))
        self.assertEqual(manifest.count('android:targetActivity=".MainActivity"'), len(check.ICONS))
        self.assertEqual(manifest.count('android:enabled="true"'), 1)
        self.assertIn('android:name=".MainActivity"\n            android:exported="false"', manifest)
        declared = set(re.findall(r'<uses-permission android:name="([^"]+)"', manifest))
        allowed = {p for p in check.ALLOWED_PERMISSIONS if p.startswith("android.permission.")}
        self.assertEqual(declared, allowed)  # each one with its threat row, nothing more
        self.assertNotIn("usesCleartextTraffic", manifest)

    def test_keys_never_enter_git(self):
        ignore = (APP / ".gitignore").read_text()
        for pattern in ("*.jks", "*.keystore", "local.properties"):
            self.assertIn(pattern, ignore)



class TrojanSourceTest(unittest.TestCase):
    """CVE-2021-42574: invisible bidi or zero width characters make code read differently than
    it runs. Tests that need them must write escapes such as \\u202E."""
    HIDDEN = re.compile("[\u202a-\u202e\u2066-\u2069\u200b-\u200f\u2028\u2029\ufeff]")

    def test_no_literal_hidden_characters_in_code(self):
        files = [p for p in APP.rglob("*") if p.suffix in (".kt", ".kts", ".xml", ".py")
                 and "build" not in p.parts and ".gradle" not in p.parts
                 and p.name != "verification-metadata.xml"]
        files += list(ROOT.glob("*.py")) + list((ROOT / "systemd").iterdir())
        files += list((ROOT / "tests").glob("*.py"))  # tests too: escapes, never the characters
        self.assertGreater(len(files), 20)
        for f in files:
            with self.subTest(f=str(f.relative_to(ROOT))):
                self.assertIsNone(self.HIDDEN.search(f.read_text(encoding="utf-8", errors="replace")))


class MarkdownViewCallTest(unittest.TestCase):
    """MarkdownView(blocks, opens, link): a trailing lambda binds to link, the web link handler,
    not opens. NotesScreen did that: every wikilink drew as "no such note" and web links became
    tappable (119). Handlers go by name."""
    TRAILING = re.compile(r"MarkdownView\(.*\)\s*\{\s*\w+\s*->")

    def test_handlers_are_passed_by_name(self):
        files = [p for p in (APP / "app" / "src" / "main").rglob("*.kt")]
        calls = 0
        for f in files:
            for n, line in enumerate(f.read_text().splitlines(), 1):
                if "MarkdownView(" in line and "fun MarkdownView" not in line:
                    calls += 1
                    self.assertIsNone(self.TRAILING.search(line), f"{f.name}:{n}")
        self.assertGreater(calls, 2)

if __name__ == "__main__":
    unittest.main()
