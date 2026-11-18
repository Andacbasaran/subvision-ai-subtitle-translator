"""
SubVision AI — Windows Çalıştırılabilir (.exe) Derleme Aracı
1. Kök dizinde özel ikonlu ve tüm kaynak dosyaları (main.py, ocr_engine.py, translator.py,
   overlay_ui.py, glossary.py, benchmark.py, requirements.txt, setup_bootstrap.ps1) kendi içine
   gömülü (Self-Extracting & Self-Bootstrapping) yerel Windows başlatıcısı (SubVisionAI.exe) üretir.
   Böylece GitHub Releases üzerinden tek başına sadece SubVisionAI.exe indirilse bile çalışır!
2. '--pyinstaller' bayrağı verilirse PyInstaller ile bağımsız (standalone) dist/ paketi oluşturur.

Kullanım:
    python build_exe.py
    python build_exe.py --pyinstaller
"""

import os
import subprocess
import sys

EMBEDDED_FILES = [
    ("main.py", "main.py"),
    ("ocr_engine.py", "ocr_engine.py"),
    ("translator.py", "translator.py"),
    ("overlay_ui.py", "overlay_ui.py"),
    ("glossary.py", "glossary.py"),
    ("benchmark.py", "benchmark.py"),
    ("requirements.txt", "requirements.txt"),
    ("setup_bootstrap.ps1", "setup_bootstrap.ps1"),
    ("baslat.bat", "baslat.bat"),
    ("assets/app_icon.ico", "assets/app_icon.ico"),
]

LauncherCSharpSource = r"""
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

namespace SubVisionAI
{
    static class Program
    {
        private static readonly string[,] EmbeddedMap = new string[,]
        {
            { "res_main.py", "main.py" },
            { "res_ocr_engine.py", "ocr_engine.py" },
            { "res_translator.py", "translator.py" },
            { "res_overlay_ui.py", "overlay_ui.py" },
            { "res_glossary.py", "glossary.py" },
            { "res_benchmark.py", "benchmark.py" },
            { "res_requirements.txt", "requirements.txt" },
            { "res_setup_bootstrap.ps1", "setup_bootstrap.ps1" },
            { "res_baslat.bat", "baslat.bat" },
            { "res_app_icon.ico", "assets\\app_icon.ico" }
        };

        private static void EnsurePayloadExtracted(string appDir)
        {
            Assembly asm = Assembly.GetExecutingAssembly();
            int count = EmbeddedMap.GetLength(0);
            for (int i = 0; i < count; i++)
            {
                string resName = EmbeddedMap[i, 0];
                string relPath = EmbeddedMap[i, 1];
                string destPath = Path.Combine(appDir, relPath);

                if (!File.Exists(destPath))
                {
                    string parent = Path.GetDirectoryName(destPath);
                    if (!string.IsNullOrEmpty(parent) && !Directory.Exists(parent))
                    {
                        Directory.CreateDirectory(parent);
                    }
                    using (Stream s = asm.GetManifestResourceStream(resName))
                    {
                        if (s != null)
                        {
                            using (FileStream fs = new FileStream(destPath, FileMode.Create, FileAccess.Write))
                            {
                                s.CopyTo(fs);
                            }
                        }
                    }
                }
            }
        }

        [STAThread]
        static void Main()
        {
            string appDir = AppDomain.CurrentDomain.BaseDirectory;

            // Eger kullanici GitHub Releases'tan sadece SubVisionAI.exe dosyasini indirdiyse
            // gomulu kaynak kodlari ve bootstrapper'i bulundugu klasore otomatik cikar!
            EnsurePayloadExtracted(appDir);

            string venvPyw = Path.Combine(appDir, ".venv", "Scripts", "pythonw.exe");
            string runtimePyw = Path.Combine(appDir, "runtime", "pythonw.exe");
            string runtimeMarker = Path.Combine(appDir, "runtime", ".deps_installed");
            string mainPy = Path.Combine(appDir, "main.py");
            string bootstrapPs1 = Path.Combine(appDir, "setup_bootstrap.ps1");

            string targetPyw = null;
            if (File.Exists(venvPyw))
                targetPyw = venvPyw;
            else if (File.Exists(runtimePyw) && File.Exists(runtimeMarker))
                targetPyw = runtimePyw;

            if (targetPyw != null && File.Exists(mainPy))
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = targetPyw;
                psi.Arguments = "\"" + mainPy + "\"";
                psi.WorkingDirectory = appDir;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                Process.Start(psi);
            }
            else if (File.Exists(bootstrapPs1))
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = "powershell.exe";
                psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + bootstrapPs1 + "\"";
                psi.WorkingDirectory = appDir;
                psi.UseShellExecute = true;
                Process.Start(psi);
            }
            else
            {
                MessageBox.Show(
                    "SubVision AI başlatılamadı: Kurulum betiği (setup_bootstrap.ps1) bulunamadı.",
                    "SubVision AI",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
            }
        }
    }
}
"""


def build_native_exe(base_dir: str) -> bool:
    csc_candidates = [
        r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
    ]
    csc_path = next((p for p in csc_candidates if os.path.exists(p)), None)
    if not csc_path:
        print("[!] Microsoft .NET Framework csc.exe bulunamadı.")
        return False

    cs_file = os.path.join(base_dir, "_launcher_tmp.cs")
    exe_file = os.path.join(base_dir, "SubVisionAI.exe")
    ico_file = os.path.join(base_dir, "assets", "app_icon.ico")

    with open(cs_file, "w", encoding="utf-8-sig") as f:
        f.write(LauncherCSharpSource.strip())

    cmd = [
        csc_path,
        "/nologo",
        "/target:winexe",
        "/optimize+",
        f"/out:{exe_file}",
    ]
    if os.path.exists(ico_file):
        cmd.append(f"/win32icon:{ico_file}")

    for rel_src, _ in EMBEDDED_FILES:
        abs_src = os.path.join(base_dir, rel_src.replace("/", os.sep))
        res_id = "res_" + os.path.basename(rel_src)
        if os.path.exists(abs_src):
            cmd.append(f"/resource:{abs_src},{res_id}")

    cmd.append(cs_file)

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0 and os.path.exists(exe_file):
            size_kb = os.path.getsize(exe_file) / 1024.0
            print(
                f"[OK] Self-Extracting & Self-Bootstrapping Windows .exe üretildi: {exe_file} ({size_kb:.1f} KB)"
            )
            return True
        print(f"[HATA] Derleme başarısız: {res.stdout}\n{res.stderr}")
        return False
    finally:
        if os.path.exists(cs_file):
            os.remove(cs_file)


def build_pyinstaller_bundle(base_dir: str) -> None:
    print("[*] PyInstaller bağımsız (standalone) paket derlemesi başlatılıyor...")
    ico_file = os.path.join(base_dir, "assets", "app_icon.ico")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name",
        "SubVisionAI",
        "--collect-all",
        "rapidocr_onnxruntime",
        "--collect-all",
        "ctranslate2",
        "--collect-all",
        "onnxruntime",
    ]
    if os.path.exists(ico_file):
        cmd.extend(["--icon", ico_file])
    cmd.append(os.path.join(base_dir, "main.py"))
    subprocess.run(cmd, cwd=base_dir, check=True)
    print("[OK] PyInstaller paketi 'dist/SubVisionAI' klasörüne çıkartıldı.")


if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    build_native_exe(root)
    if "--pyinstaller" in sys.argv:
        build_pyinstaller_bundle(root)
