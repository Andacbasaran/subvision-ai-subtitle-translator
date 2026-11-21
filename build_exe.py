"""
SubVision AI — Windows Dijital İmzalı Kurulum Yardımcısı, Uninstaller & Standalone Paket Derleme Aracı (v1.3)

Özellikler:
1. Authenticode SHA-256 Dijital İmzalama + RFC 3161 Zaman Damgası (DigiCert Timestamp):
   - Üretilen tüm .exe dosyalarını (SubVisionAI.exe, SubVisionAI-Uninstaller.exe,
     PyInstaller dist/SubVisionAI/SubVisionAI.exe ve Inno Setup SubVisionAI-Setup-*.exe)
     X.509 RSA-3072 SHA-256 kod imzalama sertifikasıyla otomatik imzalar.
   - Harici PFX sertifikası (SUBVISION_CERT_PFX / SUBVISION_CERT_PASS) varsa onu kullanır;
     yoksa yerel yayıncı sertifikası üretip açık anahtarı 'assets/SubVisionAI-Publisher.cer' olarak dışa aktarır.
2. Windows Defender / SmartScreen Dostu İnteraktif Kurulum Yardımcısı (SubVisionAI.exe):
   - Kullanıcı onayı olmadan arka planda dosya çıkartan "Silent Dropper" davranışını tamamen kaldırır.
   - İlk çalıştırmada kullanıcıya kurulum seçeneklerini (Masaüstü kısayolu, Başlat menüsü & Windows
     Yüklü Uygulamalar kaydı, Yayıncı sertifikası güven kaydı) soran modern koyu temalı GUI açar.
   - WebClient.DownloadFileAsync veya Process.Kill() gibi AV sezgisel (heuristic) tetikleyicilerini
     kullanmaz; standart HttpWebRequest akışı ve 64-bit (/platform:x64 /deterministic) PE32+ başlığı kullanır.
3. Opsiyonel Bileşen Seçimli Kaldırma Yardımcısı (SubVisionAI-Uninstaller.exe & SubVisionAI.exe --uninstall):
   - Program ile birlikte yüklenen her bileşenin disk boyutunu (MB) hesaplar ve kullanıcıya
     opsiyonel olarak seçip silme imkanı sunar:
       * Ana uygulama dosyaları, kısayollar ve Windows Yüklü Uygulamalar kaydı
       * Taşınabilir Python 3.11 çalışma ortamı ve kütüphaneler (runtime/ - ~340 MB)
       * İndirilen Yapay Zeka Çeviri Modeli (models/opus-en-tr-ct2 - ~227 MB)
       * Kişisel kullanıcı ayarları ve ROI kalibrasyonu (user_settings.json)
       * Yayıncı dijital imza sertifikası kaydı
"""

import os
import subprocess
import sys
from typing import List, Optional

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

APP_VERSION = "1.3.0.0"

EMBEDDED_FILES = [
    ("main.py", "main.py"),
    ("hardware.py", "hardware.py"),
    ("ocr_engine.py", "ocr_engine.py"),
    ("translator.py", "translator.py"),
    ("overlay_ui.py", "overlay_ui.py"),
    ("glossary.py", "glossary.py"),
    ("benchmark.py", "benchmark.py"),
    ("test_pipeline.py", "test_pipeline.py"),
    ("requirements.txt", "requirements.txt"),
    ("assets/app_icon.ico", "assets/app_icon.ico"),
    ("assets/app_icon.png", "assets/app_icon.png"),
]

AppManifestXml = r"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity
    version="1.3.0.0"
    processorArchitecture="amd64"
    name="SubVisionAI.Studio"
    type="win32"
  />
  <description>SubVision AI Real-Time Subtitle Studio Setup and Uninstaller</description>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false" />
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <!-- Windows 10 / Windows 11 -->
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}" />
      <!-- Windows 8.1 -->
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}" />
      <!-- Windows 8 -->
      <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}" />
      <!-- Windows 7 -->
      <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}" />
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
    </windowsSettings>
  </application>
</assembly>
"""

# Windows .NET Framework 4.x csc.exe (C# 5.0 uyumlu)
# Hem Kurulum Yardımcısını (SetupWizardForm) hem de Opsiyonel Kaldırma Yardımcısını (UninstallWizardForm) içerir.
LauncherCSharpSource = r"""
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("SubVision AI — Real-Time Subtitle Studio")]
[assembly: AssemblyDescription("SubVision AI Setup Assistant, Launcher and Component Uninstaller")]
[assembly: AssemblyConfiguration("Release x64")]
[assembly: AssemblyCompany("SubVision AI Open Source")]
[assembly: AssemblyProduct("SubVision AI Studio")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Andac Basaran & SubVision AI Contributors (MIT License)")]
[assembly: AssemblyTrademark("SubVision AI")]
[assembly: AssemblyCulture("")]
[assembly: AssemblyVersion("1.3.0.0")]
[assembly: AssemblyFileVersion("1.3.0.0")]

namespace SubVisionAI
{
    internal sealed class FlatProgressBar : Control
    {
        private int _value;
        private int _maximum;
        private Color _trackColor;
        private Color _fillColor;

        public FlatProgressBar()
        {
            _value = 0;
            _maximum = 100;
            _trackColor = Color.FromArgb(24, 24, 29);
            _fillColor = Color.FromArgb(59, 130, 246);
            this.DoubleBuffered = true;
            this.Height = 10;
        }

        public int Maximum
        {
            get { return _maximum; }
            set { _maximum = value < 1 ? 1 : value; Invalidate(); }
        }

        public int Value
        {
            get { return _value; }
            set
            {
                int clamped = value;
                if (clamped < 0) clamped = 0;
                if (clamped > _maximum) clamped = _maximum;
                if (_value != clamped)
                {
                    _value = clamped;
                    Invalidate();
                }
            }
        }

        public Color FillColor
        {
            get { return _fillColor; }
            set { _fillColor = value; Invalidate(); }
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;

            Rectangle rect = new Rectangle(0, 0, this.Width - 1, this.Height - 1);
            using (SolidBrush bg = new SolidBrush(_trackColor))
            {
                g.FillRectangle(bg, 0, 0, this.Width, this.Height);
            }

            if (_value > 0 && _maximum > 0)
            {
                int fillW = (int)Math.Round((double)this.Width * _value / _maximum);
                if (fillW < 2) fillW = 2;
                using (SolidBrush fg = new SolidBrush(_fillColor))
                {
                    g.FillRectangle(fg, 0, 0, fillW, this.Height);
                }
            }

            using (Pen border = new Pen(Color.FromArgb(39, 39, 46), 1))
            {
                g.DrawRectangle(border, rect);
            }
        }
    }

    internal static class SystemIntegrationHelper
    {
        public const string UninstallRegKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\SubVisionAI";
        public const string CertSubjectMatch = "SubVision AI Open Source";

        private static readonly string[,] EmbeddedMap = new string[,]
        {
            { "res_main.py", "main.py" },
            { "res_hardware.py", "hardware.py" },
            { "res_ocr_engine.py", "ocr_engine.py" },
            { "res_translator.py", "translator.py" },
            { "res_overlay_ui.py", "overlay_ui.py" },
            { "res_glossary.py", "glossary.py" },
            { "res_benchmark.py", "benchmark.py" },
            { "res_test_pipeline.py", "test_pipeline.py" },
            { "res_requirements.txt", "requirements.txt" },
            { "res_app_icon.ico", "assets\\app_icon.ico" },
            { "res_app_icon.png", "assets\\app_icon.png" },
            { "res_SubVisionAI-Publisher.cer", "assets\\SubVisionAI-Publisher.cer" }
        };

        public static void ExtractEmbeddedFiles(string appDir, Action<string> logCallback)
        {
            Assembly asm = Assembly.GetExecutingAssembly();
            int count = EmbeddedMap.GetLength(0);
            for (int i = 0; i < count; i++)
            {
                string resName = EmbeddedMap[i, 0];
                string relPath = EmbeddedMap[i, 1];
                string destPath = Path.Combine(appDir, relPath);

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
                        if (logCallback != null)
                        {
                            logCallback("[OK] Çıkartıldı: " + relPath);
                        }
                    }
                }
            }

            // Kaldırma yardımcısını (SubVisionAI-Uninstaller.exe) aynı imzalı ikili dosyadan oluştur
            try
            {
                string currentExe = Application.ExecutablePath;
                string uninstallerExe = Path.Combine(appDir, "SubVisionAI-Uninstaller.exe");
                if (!string.Equals(Path.GetFullPath(currentExe), Path.GetFullPath(uninstallerExe), StringComparison.OrdinalIgnoreCase))
                {
                    File.Copy(currentExe, uninstallerExe, true);
                    if (logCallback != null)
                    {
                        logCallback("[OK] Kaldırma yardımcısı hazırlandı: SubVisionAI-Uninstaller.exe");
                    }
                }
            }
            catch { }
        }

        public static bool InstallPublisherCertificateToUserStore(string appDir, Action<string> logCallback)
        {
            try
            {
                X509Certificate2 cert = null;
                string cerPath = Path.Combine(appDir, "assets", "SubVisionAI-Publisher.cer");
                if (File.Exists(cerPath))
                {
                    cert = new X509Certificate2(cerPath);
                }
                else
                {
                    X509Certificate signer = X509Certificate.CreateFromSignedFile(Application.ExecutablePath);
                    if (signer != null)
                    {
                        cert = new X509Certificate2(signer);
                    }
                }

                if (cert == null) return false;

                StoreName[] stores = new StoreName[] { StoreName.TrustedPublisher, StoreName.TrustedPeople };
                foreach (StoreName sn in stores)
                {
                    try
                    {
                        X509Store store = new X509Store(sn, StoreLocation.CurrentUser);
                        store.Open(OpenFlags.ReadWrite);
                        X509Certificate2Collection existing = store.Certificates.Find(X509FindType.FindByThumbprint, cert.Thumbprint, false);
                        if (existing == null || existing.Count == 0)
                        {
                            store.Add(cert);
                        }
                        store.Close();
                    }
                    catch { }
                }

                if (logCallback != null)
                {
                    logCallback("[OK] Yayıncı sertifikası doğrulanmış kullanıcı deposuna eklendi (" + cert.Thumbprint + ").");
                }
                return true;
            }
            catch (Exception ex)
            {
                if (logCallback != null)
                {
                    logCallback("[BİLGİ] Sertifika kaydı atlandı: " + ex.Message);
                }
                return false;
            }
        }

        public static void RemovePublisherCertificateFromUserStore()
        {
            StoreName[] stores = new StoreName[] { StoreName.TrustedPublisher, StoreName.TrustedPeople };
            foreach (StoreName sn in stores)
            {
                try
                {
                    X509Store store = new X509Store(sn, StoreLocation.CurrentUser);
                    store.Open(OpenFlags.ReadWrite);
                    List<X509Certificate2> toRemove = new List<X509Certificate2>();
                    foreach (X509Certificate2 c in store.Certificates)
                    {
                        if (c.Subject != null && c.Subject.IndexOf(CertSubjectMatch, StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            toRemove.Add(c);
                        }
                    }
                    foreach (X509Certificate2 rem in toRemove)
                    {
                        store.Remove(rem);
                    }
                    store.Close();
                }
                catch { }
            }
        }

        public static void CreateShortcut(string shortcutPath, string targetPath, string workingDir, string iconPath, string description)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return;
                object shell = Activator.CreateInstance(shellType);
                object shortcut = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { shortcutPath });
                if (shortcut == null) return;

                Type scType = shortcut.GetType();
                scType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { targetPath });
                scType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { workingDir });
                scType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { description });
                if (!string.IsNullOrEmpty(iconPath) && File.Exists(iconPath))
                {
                    scType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { iconPath });
                }
                scType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
            }
            catch { }
        }

        public static void RegisterShortcutsAndUninstaller(string appDir, bool createDesktop, bool registerSystem, Action<string> logCallback)
        {
            string mainExe = Path.Combine(appDir, "SubVisionAI.exe");
            if (!File.Exists(mainExe)) mainExe = Application.ExecutablePath;
            string uninstallerExe = Path.Combine(appDir, "SubVisionAI-Uninstaller.exe");
            if (!File.Exists(uninstallerExe)) uninstallerExe = mainExe;
            string iconPath = Path.Combine(appDir, "assets", "app_icon.ico");

            if (createDesktop)
            {
                try
                {
                    string desktopDir = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                    string lnkPath = Path.Combine(desktopDir, "SubVision AI.lnk");
                    CreateShortcut(lnkPath, mainExe, appDir, iconPath, "SubVision AI — Lokal Yapay Zeka Altyazı Stüdyosu");
                    if (logCallback != null) logCallback("[OK] Masaüstü kısayolu oluşturuldu.");
                }
                catch { }
            }

            if (registerSystem)
            {
                try
                {
                    string startMenuDir = Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.Programs),
                        "SubVision AI"
                    );
                    if (!Directory.Exists(startMenuDir)) Directory.CreateDirectory(startMenuDir);

                    CreateShortcut(
                        Path.Combine(startMenuDir, "SubVision AI.lnk"),
                        mainExe,
                        appDir,
                        iconPath,
                        "SubVision AI — Lokal Yapay Zeka Altyazı Stüdyosu"
                    );
                    CreateShortcut(
                        Path.Combine(startMenuDir, "SubVision AI Kaldır (Uninstall).lnk"),
                        uninstallerExe,
                        appDir,
                        iconPath,
                        "SubVision AI Bileşen ve Kaldırma Yardımcısı"
                    );
                }
                catch { }

                try
                {
                    using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallRegKeyPath))
                    {
                        if (key != null)
                        {
                            key.SetValue("DisplayName", "SubVision AI — Real-Time Subtitle Studio");
                            key.SetValue("DisplayVersion", "1.3.0");
                            key.SetValue("Publisher", "SubVision AI Open Source");
                            key.SetValue("DisplayIcon", File.Exists(iconPath) ? iconPath : mainExe);
                            key.SetValue("InstallLocation", appDir);
                            key.SetValue("UninstallString", "\"" + uninstallerExe + "\" --uninstall");
                            key.SetValue("QuietUninstallString", "\"" + uninstallerExe + "\" --uninstall");
                            key.SetValue("URLInfoAbout", "https://github.com/Andacbasaran/subvision-ai-subtitle-translator");
                            key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                            key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                            long sizeKb = GetDirectorySizeBytes(appDir) / 1024;
                            if (sizeKb > 0)
                            {
                                key.SetValue("EstimatedSize", (int)Math.Min(int.MaxValue, sizeKb), RegistryValueKind.DWord);
                            }
                        }
                    }
                    if (logCallback != null) logCallback("[OK] Windows Yüklü Uygulamalar (Uninstaller) kaydı oluşturuldu.");
                }
                catch { }
            }
        }

        public static void RemoveShortcutsAndRegistry()
        {
            try
            {
                string desktopLnk = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "SubVision AI.lnk");
                if (File.Exists(desktopLnk)) File.Delete(desktopLnk);
            }
            catch { }

            try
            {
                string startMenuDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "SubVision AI");
                if (Directory.Exists(startMenuDir)) Directory.Delete(startMenuDir, true);
            }
            catch { }

            try
            {
                Registry.CurrentUser.DeleteSubKeyTree(UninstallRegKeyPath, false);
            }
            catch { }
        }

        public static long GetDirectorySizeBytes(string dirPath)
        {
            if (string.IsNullOrEmpty(dirPath) || !Directory.Exists(dirPath)) return 0;
            long total = 0;
            try
            {
                string[] files = Directory.GetFiles(dirPath, "*", SearchOption.AllDirectories);
                for (int i = 0; i < files.Length; i++)
                {
                    try { total += new FileInfo(files[i]).Length; } catch { }
                }
            }
            catch { }
            return total;
        }

        public static string FormatSizeMb(long bytes)
        {
            if (bytes <= 0) return "0 MB";
            double mb = bytes / (1024.0 * 1024.0);
            if (mb < 0.1) return "< 0.1 MB";
            return string.Format("{0:F1} MB", mb);
        }
    }

    // ═════════════════════════════════════════════════════════════════════════
    // 1. İNTERAKTİF KURULUM YARDIMCISI (SETUP WIZARD FORM)
    // ═════════════════════════════════════════════════════════════════════════
    internal sealed class SetupWizardForm : Form
    {
        private const string PythonEmbedUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip";
        private const string GetPipUrl = "https://bootstrap.pypa.io/get-pip.py";
        private const string VcRedistDocsUrl = "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist";

        private readonly string _appDir;
        private readonly string _runtimeDir;

        private Label _lblTitle;
        private Label _lblSubtitle;
        private Label _lblSecurityBadge;
        private CheckBox _chkDesktopShortcut;
        private CheckBox _chkRegisterUninstaller;
        private CheckBox _chkTrustPublisherCert;
        private Label _lblStep;
        private Label _lblPercent;
        private FlatProgressBar _progressBar;
        private Label _lblDetail;
        private Button _btnStartInstall;
        private Button _btnToggleLog;
        private Button _btnOpenUninstaller;
        private Button _btnCancel;
        private TextBox _txtLog;

        private bool _logExpanded;
        private volatile bool _cancelRequested;
        private volatile bool _isInstalling;
        private Thread _workerThread;

        public bool SetupSucceeded { get; private set; }

        public SetupWizardForm(string appDir)
        {
            _appDir = appDir;
            _runtimeDir = Path.Combine(appDir, "runtime");
            _logExpanded = false;
            _cancelRequested = false;
            _isInstalling = false;
            SetupSucceeded = false;

            InitializeUi();
        }

        private void InitializeUi()
        {
            Color bgDark = Color.FromArgb(9, 9, 11);
            Color cardDark = Color.FromArgb(17, 17, 20);
            Color borderCol = Color.FromArgb(36, 36, 41);
            Color textPrimary = Color.FromArgb(244, 244, 245);
            Color textMuted = Color.FromArgb(148, 163, 184);
            Color accent = Color.FromArgb(37, 99, 235);
            Color greenCol = Color.FromArgb(16, 185, 129);

            this.Text = "SubVision AI v1.3 — Kurulum Yardımcısı";
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = true;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = bgDark;
            this.ForeColor = textPrimary;
            this.Font = new Font("Segoe UI", 9.25F, FontStyle.Regular);
            this.ClientSize = new Size(580, 360);

            string iconPath = Path.Combine(_appDir, "assets", "app_icon.ico");
            if (File.Exists(iconPath))
            {
                try { this.Icon = new Icon(iconPath); } catch { }
            }

            Panel mainCard = new Panel();
            mainCard.BackColor = cardDark;
            mainCard.Location = new Point(20, 16);
            mainCard.Size = new Size(540, 282);
            mainCard.Paint += delegate(object s, PaintEventArgs e)
            {
                using (Pen p = new Pen(borderCol, 1))
                {
                    e.Graphics.DrawRectangle(p, 0, 0, mainCard.Width - 1, mainCard.Height - 1);
                }
            };
            this.Controls.Add(mainCard);

            _lblTitle = new Label();
            _lblTitle.Text = "SubVision AI  v1.3 — Kurulum Yardımcısı";
            _lblTitle.Font = new Font("Segoe UI Semibold", 13.5F, FontStyle.Bold);
            _lblTitle.ForeColor = textPrimary;
            _lblTitle.Location = new Point(18, 14);
            _lblTitle.AutoSize = true;
            mainCard.Controls.Add(_lblTitle);

            _lblSecurityBadge = new Label();
            _lblSecurityBadge.Text = "✓ SHA-256 Authenticode Dijital İmzalı   ·   Yönetici İzni Gerektirmez (asInvoker)";
            _lblSecurityBadge.Font = new Font("Segoe UI Semibold", 8.25F, FontStyle.Bold);
            _lblSecurityBadge.ForeColor = greenCol;
            _lblSecurityBadge.Location = new Point(18, 42);
            _lblSecurityBadge.Size = new Size(504, 18);
            mainCard.Controls.Add(_lblSecurityBadge);

            _lblSubtitle = new Label();
            _lblSubtitle.Text = "Kurulum seçeneklerini belirleyip 'Kurulumu Başlat' butonuna tıklayın. İşlem siyah terminal açmadan tamamlanır.";
            _lblSubtitle.Font = new Font("Segoe UI", 8.5F, FontStyle.Regular);
            _lblSubtitle.ForeColor = textMuted;
            _lblSubtitle.Location = new Point(18, 64);
            _lblSubtitle.Size = new Size(504, 20);
            mainCard.Controls.Add(_lblSubtitle);

            _chkDesktopShortcut = new CheckBox();
            _chkDesktopShortcut.Text = "Masaüstü kısayolu oluştur (SubVision AI)";
            _chkDesktopShortcut.Checked = true;
            _chkDesktopShortcut.ForeColor = textPrimary;
            _chkDesktopShortcut.Location = new Point(20, 94);
            _chkDesktopShortcut.Size = new Size(490, 22);
            mainCard.Controls.Add(_chkDesktopShortcut);

            _chkRegisterUninstaller = new CheckBox();
            _chkRegisterUninstaller.Text = "Başlat Menüsü ve Windows 'Yüklü Uygulamalar' kaldırıcı (Uninstaller) kaydı oluştur";
            _chkRegisterUninstaller.Checked = true;
            _chkRegisterUninstaller.ForeColor = textPrimary;
            _chkRegisterUninstaller.Location = new Point(20, 118);
            _chkRegisterUninstaller.Size = new Size(500, 22);
            mainCard.Controls.Add(_chkRegisterUninstaller);

            _chkTrustPublisherCert = new CheckBox();
            _chkTrustPublisherCert.Text = "Yayıncı dijital imza sertifikasını kullanıcı güvenilir deposuna kaydet (Uyarı önleyici)";
            _chkTrustPublisherCert.Checked = true;
            _chkTrustPublisherCert.ForeColor = textPrimary;
            _chkTrustPublisherCert.Location = new Point(20, 142);
            _chkTrustPublisherCert.Size = new Size(500, 22);
            mainCard.Controls.Add(_chkTrustPublisherCert);

            _lblStep = new Label();
            _lblStep.Text = "Kurulumu başlatmak için hazır.";
            _lblStep.Font = new Font("Segoe UI Semibold", 9.25F, FontStyle.Bold);
            _lblStep.ForeColor = Color.FromArgb(226, 232, 240);
            _lblStep.Location = new Point(18, 178);
            _lblStep.Size = new Size(430, 20);
            mainCard.Controls.Add(_lblStep);

            _lblPercent = new Label();
            _lblPercent.Text = "0%";
            _lblPercent.Font = new Font("Segoe UI Semibold", 9.25F, FontStyle.Bold);
            _lblPercent.ForeColor = Color.FromArgb(59, 130, 246);
            _lblPercent.TextAlign = ContentAlignment.MiddleRight;
            _lblPercent.Location = new Point(458, 178);
            _lblPercent.Size = new Size(64, 20);
            mainCard.Controls.Add(_lblPercent);

            _progressBar = new FlatProgressBar();
            _progressBar.Location = new Point(18, 204);
            _progressBar.Size = new Size(504, 12);
            mainCard.Controls.Add(_progressBar);

            _lblDetail = new Label();
            _lblDetail.Text = "Hedef Klasör: " + _appDir;
            _lblDetail.Font = new Font("Segoe UI", 8.25F, FontStyle.Regular);
            _lblDetail.ForeColor = textMuted;
            _lblDetail.Location = new Point(18, 226);
            _lblDetail.Size = new Size(504, 36);
            mainCard.Controls.Add(_lblDetail);

            _btnToggleLog = CreateFlatButton("Detayları Göster", new Point(20, 310), new Size(126, 34), cardDark, textMuted, borderCol);
            _btnToggleLog.Click += delegate { ToggleLogPanel(); };
            this.Controls.Add(_btnToggleLog);

            _btnOpenUninstaller = CreateFlatButton("Kaldırma Aracı", new Point(154, 310), new Size(120, 34), cardDark, textMuted, borderCol);
            _btnOpenUninstaller.Click += delegate { OpenUninstallerDialog(); };
            this.Controls.Add(_btnOpenUninstaller);

            _btnStartInstall = CreateFlatButton("Kurulumu Başlat", new Point(304, 310), new Size(140, 34), accent, Color.White, accent);
            _btnStartInstall.Click += delegate { StartSetupAsync(); };
            this.Controls.Add(_btnStartInstall);

            _btnCancel = CreateFlatButton("Kapat", new Point(452, 310), new Size(108, 34), cardDark, textPrimary, borderCol);
            _btnCancel.Click += delegate { RequestCancelAndClose(); };
            this.Controls.Add(_btnCancel);

            _txtLog = new TextBox();
            _txtLog.Multiline = true;
            _txtLog.ReadOnly = true;
            _txtLog.ScrollBars = ScrollBars.Vertical;
            _txtLog.BackColor = Color.FromArgb(13, 13, 16);
            _txtLog.ForeColor = Color.FromArgb(161, 161, 170);
            _txtLog.BorderStyle = BorderStyle.FixedSingle;
            _txtLog.Font = new Font("Consolas", 8.5F, FontStyle.Regular);
            _txtLog.Location = new Point(20, 356);
            _txtLog.Size = new Size(540, 150);
            _txtLog.Visible = false;
            this.Controls.Add(_txtLog);

            this.Shown += delegate
            {
                CheckVcRedistWarning();
            };

            this.FormClosing += delegate(object sender, FormClosingEventArgs e)
            {
                if (_isInstalling && !SetupSucceeded)
                {
                    _cancelRequested = true;
                }
            };
        }

        public static Button CreateFlatButton(string text, Point loc, Size size, Color bg, Color fg, Color border)
        {
            Button btn = new Button();
            btn.Text = text;
            btn.Location = loc;
            btn.Size = size;
            btn.FlatStyle = FlatStyle.Flat;
            btn.FlatAppearance.BorderColor = border;
            btn.FlatAppearance.BorderSize = 1;
            btn.BackColor = bg;
            btn.ForeColor = fg;
            btn.Cursor = Cursors.Hand;
            btn.Font = new Font("Segoe UI Semibold", 9F, FontStyle.Regular);
            return btn;
        }

        private void OpenUninstallerDialog()
        {
            using (UninstallWizardForm uninst = new UninstallWizardForm(_appDir))
            {
                uninst.ShowDialog(this);
            }
        }

        private void ToggleLogPanel()
        {
            _logExpanded = !_logExpanded;
            _txtLog.Visible = _logExpanded;
            _btnToggleLog.Text = _logExpanded ? "Detayları Gizle" : "Detayları Göster";
            this.ClientSize = _logExpanded ? new Size(580, 520) : new Size(580, 360);
        }

        private void EnsureLogExpanded()
        {
            if (!_logExpanded)
            {
                ToggleLogPanel();
            }
        }

        private void CheckVcRedistWarning()
        {
            try
            {
                string sysDir = Environment.GetFolderPath(Environment.SpecialFolder.System);
                string dll1 = Path.Combine(sysDir, "vcruntime140_1.dll");
                string dll2 = Path.Combine(sysDir, "vcruntime140.dll");
                if (!File.Exists(dll1) && !File.Exists(dll2))
                {
                    DialogResult dr = MessageBox.Show(
                        "Bilgisayarınızda Microsoft Visual C++ 2015-2022 Redistributable (x64) bileşeni bulunamadı.\n\n" +
                        "Yapay zeka motorunun sorunsuz çalışması için bu resmi Microsoft bileşeninin yüklü olması önerilir.\n\n" +
                        "Resmi Microsoft indirme sayfasını tarayıcınızda açmak ister misiniz?",
                        "SubVision AI — Sistem Gereksinimi",
                        MessageBoxButtons.YesNo,
                        MessageBoxIcon.Information
                    );
                    if (dr == DialogResult.Yes)
                    {
                        Process.Start(new ProcessStartInfo(VcRedistDocsUrl) { UseShellExecute = true });
                    }
                }
            }
            catch { }
        }

        private void SafeUi(Action action)
        {
            if (this.IsDisposed) return;
            try
            {
                if (this.InvokeRequired)
                {
                    this.BeginInvoke(action);
                }
                else
                {
                    action();
                }
            }
            catch { }
        }

        private void UpdateProgress(string stepText, int percent, string detailText)
        {
            SafeUi(delegate
            {
                _lblStep.Text = stepText;
                _progressBar.Value = percent;
                _lblPercent.Text = percent.ToString() + "%";
                if (detailText != null)
                {
                    _lblDetail.Text = detailText;
                }
            });
        }

        private void AppendLog(string line)
        {
            if (string.IsNullOrEmpty(line)) return;
            SafeUi(delegate
            {
                if (_txtLog.TextLength > 32000)
                {
                    _txtLog.Text = _txtLog.Text.Substring(_txtLog.TextLength - 16000);
                }
                _txtLog.AppendText(line + Environment.NewLine);
            });
        }

        private void StartSetupAsync()
        {
            if (_isInstalling) return;
            _isInstalling = true;
            _cancelRequested = false;

            _btnStartInstall.Enabled = false;
            _btnStartInstall.Text = "Kuruluyor...";
            _btnOpenUninstaller.Enabled = false;
            _chkDesktopShortcut.Enabled = false;
            _chkRegisterUninstaller.Enabled = false;
            _chkTrustPublisherCert.Enabled = false;
            _btnCancel.Text = "İptal";
            _progressBar.FillColor = Color.FromArgb(59, 130, 246);

            bool optDesktop = _chkDesktopShortcut.Checked;
            bool optReg = _chkRegisterUninstaller.Checked;
            bool optCert = _chkTrustPublisherCert.Checked;

            _workerThread = new Thread(delegate() { RunSetupPipeline(optDesktop, optReg, optCert); });
            _workerThread.IsBackground = true;
            _workerThread.Start();
        }

        private void RequestCancelAndClose()
        {
            if (_isInstalling)
            {
                _cancelRequested = true;
            }
            this.DialogResult = DialogResult.Cancel;
            this.Close();
        }

        private void DownloadFileHttpStream(string url, string destPath, int basePct, int spanPct, string stepLabel)
        {
            AppendLog(">> İndiriliyor: " + url);
            HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
            req.UserAgent = "SubVisionAI-SetupAssistant/1.3";
            req.Timeout = 30000;
            req.ReadWriteTimeout = 30000;

            using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
            using (Stream netStream = resp.GetResponseStream())
            using (FileStream fileStream = new FileStream(destPath, FileMode.Create, FileAccess.Write))
            {
                long totalBytes = resp.ContentLength;
                long receivedBytes = 0;
                byte[] buffer = new byte[65536];
                int read;
                int lastReportedPct = -1;

                while ((read = netStream.Read(buffer, 0, buffer.Length)) > 0)
                {
                    if (_cancelRequested)
                    {
                        throw new OperationCanceledException("Kurulum kullanıcı tarafından iptal edildi.");
                    }
                    fileStream.Write(buffer, 0, read);
                    receivedBytes += read;

                    if (totalBytes > 0)
                    {
                        int rawPct = (int)Math.Round((receivedBytes * 100.0) / totalBytes);
                        if (rawPct != lastReportedPct)
                        {
                            lastReportedPct = rawPct;
                            int uiPct = basePct + (int)Math.Round(spanPct * (rawPct / 100.0));
                            double recvMb = receivedBytes / (1024.0 * 1024.0);
                            double totMb = totalBytes / (1024.0 * 1024.0);
                            UpdateProgress(
                                stepLabel,
                                uiPct,
                                string.Format("İndiriliyor: {0:F1} MB / {1:F1} MB", recvMb, totMb)
                            );
                        }
                    }
                }
            }
        }

        private int RunToolProcess(string fileName, string arguments, string workingDir, Action<string> onOutputLine)
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = fileName;
            psi.Arguments = arguments;
            psi.WorkingDirectory = workingDir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.StandardOutputEncoding = Encoding.UTF8;
            psi.StandardErrorEncoding = Encoding.UTF8;

            using (Process proc = new Process())
            {
                proc.StartInfo = psi;
                proc.OutputDataReceived += delegate(object s, DataReceivedEventArgs e)
                {
                    if (!string.IsNullOrEmpty(e.Data))
                    {
                        AppendLog(e.Data);
                        if (onOutputLine != null) onOutputLine(e.Data);
                    }
                };
                proc.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e)
                {
                    if (!string.IsNullOrEmpty(e.Data))
                    {
                        AppendLog(e.Data);
                    }
                };

                AppendLog(">> Çalıştırılıyor: " + Path.GetFileName(fileName) + " " + arguments);
                proc.Start();
                proc.BeginOutputReadLine();
                proc.BeginErrorReadLine();

                while (!proc.WaitForExit(250))
                {
                    if (_cancelRequested)
                    {
                        try { proc.CloseMainWindow(); } catch { }
                        break;
                    }
                }
                proc.WaitForExit(3000);
                return proc.HasExited ? proc.ExitCode : -1;
            }
        }

        private static void ExtractZipOverwrite(string zipPath, string destDir)
        {
            string fullDestRoot = Path.GetFullPath(destDir);
            if (!fullDestRoot.EndsWith(Path.DirectorySeparatorChar.ToString(), StringComparison.Ordinal))
            {
                fullDestRoot += Path.DirectorySeparatorChar;
            }

            using (ZipArchive archive = ZipFile.OpenRead(zipPath))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string targetPath = Path.GetFullPath(Path.Combine(destDir, entry.FullName));
                    if (!targetPath.StartsWith(fullDestRoot, StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }
                    if (string.IsNullOrEmpty(entry.Name))
                    {
                        Directory.CreateDirectory(targetPath);
                    }
                    else
                    {
                        string parent = Path.GetDirectoryName(targetPath);
                        if (!string.IsNullOrEmpty(parent) && !Directory.Exists(parent))
                        {
                            Directory.CreateDirectory(parent);
                        }
                        entry.ExtractToFile(targetPath, true);
                    }
                }
            }
        }

        private void PatchEmbeddedPthFile()
        {
            string pthFile = Path.Combine(_runtimeDir, "python311._pth");
            if (!File.Exists(pthFile)) return;

            string content = File.ReadAllText(pthFile, Encoding.UTF8);
            content = content.Replace("#import site", "import site");
            if (content.IndexOf("..", StringComparison.Ordinal) < 0)
            {
                content = content.TrimEnd() + Environment.NewLine + ".." + Environment.NewLine;
            }
            File.WriteAllText(pthFile, content, new UTF8Encoding(false));
            AppendLog("[OK] python311._pth site-packages desteği etkinleştirildi.");
        }

        private void RunSetupPipeline(bool createDesktop, bool registerSystem, bool trustCert)
        {
            try
            {
                ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;

                // ADIM 0: Kullanıcı onayından sonra uygulama bileşenlerini çıkart
                UpdateProgress("Uygulama dosyaları ve sertifika yapılandırılıyor...", 4, "Modüller çıkartılıyor...");
                SystemIntegrationHelper.ExtractEmbeddedFiles(_appDir, AppendLog);

                if (trustCert)
                {
                    SystemIntegrationHelper.InstallPublisherCertificateToUserStore(_appDir, AppendLog);
                }

                if (!Directory.Exists(_runtimeDir))
                {
                    Directory.CreateDirectory(_runtimeDir);
                }

                string pyExe = Path.Combine(_runtimeDir, "python.exe");
                string pyZip = Path.Combine(_runtimeDir, "python_embed.zip");
                string getPipPy = Path.Combine(_runtimeDir, "get-pip.py");
                string pipExe = Path.Combine(_runtimeDir, "Scripts", "pip.exe");
                string reqFile = Path.Combine(_appDir, "requirements.txt");
                string markerFile = Path.Combine(_runtimeDir, ".deps_installed");

                // ADIM 1: Taşınabilir Python 3.11.9
                if (!File.Exists(pyExe))
                {
                    if (_cancelRequested) throw new OperationCanceledException();
                    DownloadFileHttpStream(
                        PythonEmbedUrl,
                        pyZip,
                        8,
                        24,
                        "[1/3] Taşınabilir Python 3.11.9 indiriliyor..."
                    );

                    if (_cancelRequested) throw new OperationCanceledException();
                    UpdateProgress("[1/3] Python çalışma ortamı çıkartılıyor...", 34, "Arşiv açılıyor...");
                    ExtractZipOverwrite(pyZip, _runtimeDir);
                    try { File.Delete(pyZip); } catch { }
                    PatchEmbeddedPthFile();
                }
                else
                {
                    PatchEmbeddedPthFile();
                    UpdateProgress("[1/3] Taşınabilir Python hazır.", 34, "Mevcut Python ortamı doğrulandı.");
                }

                // ADIM 2: pip kurulumu
                if (!File.Exists(pipExe))
                {
                    if (_cancelRequested) throw new OperationCanceledException();
                    DownloadFileHttpStream(
                        GetPipUrl,
                        getPipPy,
                        36,
                        10,
                        "[2/3] Paket yöneticisi (pip) indiriliyor..."
                    );

                    if (_cancelRequested) throw new OperationCanceledException();
                    UpdateProgress("[2/3] Paket yöneticisi (pip) kuruluyor...", 48, "Yapılandırılıyor...");
                    int rcPip = RunToolProcess(pyExe, "\"" + getPipPy + "\" --no-warn-script-location", _appDir, null);
                    try { File.Delete(getPipPy); } catch { }
                    if (_cancelRequested) throw new OperationCanceledException();
                    if (rcPip != 0)
                    {
                        throw new Exception("pip kurulumu başarısız oldu (Çıkış kodu: " + rcPip + ").");
                    }
                }
                else
                {
                    UpdateProgress("[2/3] Paket yöneticisi (pip) hazır.", 52, "Doğrulandı.");
                }

                // ADIM 3: Bağımlılık kurulumu
                if (_cancelRequested) throw new OperationCanceledException();
                UpdateProgress("[3/3] Yapay zeka ve arayüz paketleri kuruluyor...", 56, "PyQt6, RapidOCR, CTranslate2 ve OpenCV hazırlanıyor...");

                int pipProgress = 58;
                int rcDeps = RunToolProcess(
                    pyExe,
                    "-m pip install --prefer-binary --no-warn-script-location --upgrade-strategy only-if-needed -r \"" + reqFile + "\"",
                    _appDir,
                    delegate(string line)
                    {
                        string trimmed = line.Trim();
                        if (trimmed.StartsWith("Collecting ", StringComparison.OrdinalIgnoreCase) ||
                            trimmed.StartsWith("Downloading ", StringComparison.OrdinalIgnoreCase) ||
                            trimmed.StartsWith("Installing collected packages", StringComparison.OrdinalIgnoreCase))
                        {
                            if (pipProgress < 94) pipProgress += 2;
                            string shortLine = trimmed.Length > 72 ? trimmed.Substring(0, 69) + "..." : trimmed;
                            UpdateProgress("[3/3] Yapay zeka paketleri kuruluyor...", pipProgress, shortLine);
                        }
                    }
                );

                if (_cancelRequested) throw new OperationCanceledException();
                if (rcDeps != 0)
                {
                    throw new Exception("Paket kurulumu sırasında hata oluştu (Çıkış kodu: " + rcDeps + ").");
                }

                File.WriteAllText(markerFile, "1.3.0", Encoding.UTF8);

                // ADIM 4: Kısayolları ve Uninstaller Kaydını Oluştur
                UpdateProgress("Kısayollar ve Kaldırma Yardımcısı kaydediliyor...", 97, "Sistem entegrasyonu tamamlanıyor...");
                SystemIntegrationHelper.RegisterShortcutsAndUninstaller(_appDir, createDesktop, registerSystem, AppendLog);

                SetupSucceeded = true;
                _isInstalling = false;

                SafeUi(delegate
                {
                    _progressBar.FillColor = Color.FromArgb(16, 185, 129);
                    _lblPercent.ForeColor = Color.FromArgb(16, 185, 129);
                });
                UpdateProgress("Kurulum tamamlandı! SubVision AI başlatılıyor...", 100, "Sonraki açılışlarda doğrudan başlayacaktır.");
                Thread.Sleep(700);

                SafeUi(delegate
                {
                    this.DialogResult = DialogResult.OK;
                    this.Close();
                });
            }
            catch (OperationCanceledException)
            {
                _isInstalling = false;
                AppendLog("[İPTAL] Kurulum kullanıcı tarafından iptal edildi.");
                SafeUi(delegate
                {
                    _btnStartInstall.Enabled = true;
                    _btnStartInstall.Text = "Tekrar Dene";
                    _btnOpenUninstaller.Enabled = true;
                });
            }
            catch (Exception ex)
            {
                _isInstalling = false;
                AppendLog("[HATA] " + ex.Message);
                SafeUi(delegate
                {
                    _progressBar.FillColor = Color.FromArgb(239, 68, 68);
                    _lblPercent.ForeColor = Color.FromArgb(239, 68, 68);
                    _lblStep.Text = "Kurulum tamamlanamadı.";
                    _lblDetail.Text = ex.Message;
                    _btnStartInstall.Enabled = true;
                    _btnStartInstall.Text = "Tekrar Dene";
                    _btnOpenUninstaller.Enabled = true;
                    _btnCancel.Text = "Kapat";
                    EnsureLogExpanded();
                });
            }
        }
    }

    // ═════════════════════════════════════════════════════════════════════════
    // 2. OPSİYONEL BİLEŞEN SEÇİMLİ KALDIRMA YARDIMCISI (UNINSTALL WIZARD FORM)
    // ═════════════════════════════════════════════════════════════════════════
    internal sealed class UninstallWizardForm : Form
    {
        private readonly string _appDir;
        private readonly string _localAppDataDir;

        private CheckBox _chkCoreApp;
        private CheckBox _chkRuntime;
        private CheckBox _chkModels;
        private CheckBox _chkSettings;
        private CheckBox _chkCert;
        private Label _lblStatus;
        private FlatProgressBar _progressBar;
        private Button _btnFullUninstall;
        private Button _btnCleanSelectedOnly;
        private Button _btnClose;

        public UninstallWizardForm(string appDir)
        {
            _appDir = appDir;
            string localRoot = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            _localAppDataDir = Path.Combine(localRoot, "SubVisionAI");
            InitializeUi();
        }

        private void InitializeUi()
        {
            Color bgDark = Color.FromArgb(9, 9, 11);
            Color cardDark = Color.FromArgb(17, 17, 20);
            Color borderCol = Color.FromArgb(36, 36, 41);
            Color textPrimary = Color.FromArgb(244, 244, 245);
            Color textMuted = Color.FromArgb(148, 163, 184);
            Color dangerCol = Color.FromArgb(220, 38, 38);
            Color amberCol = Color.FromArgb(217, 119, 6);

            this.Text = "SubVision AI — Kaldırma ve Bileşen Temizleme Yardımcısı";
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = true;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = bgDark;
            this.ForeColor = textPrimary;
            this.Font = new Font("Segoe UI", 9.25F, FontStyle.Regular);
            this.ClientSize = new Size(600, 395);

            string iconPath = Path.Combine(_appDir, "assets", "app_icon.ico");
            if (File.Exists(iconPath))
            {
                try { this.Icon = new Icon(iconPath); } catch { }
            }

            // Bileşen boyutlarını hesapla
            long runtimeBytes = SystemIntegrationHelper.GetDirectorySizeBytes(Path.Combine(_appDir, "runtime"));
            long localModelsBytes = SystemIntegrationHelper.GetDirectorySizeBytes(Path.Combine(_appDir, "models"))
                                  + SystemIntegrationHelper.GetDirectorySizeBytes(Path.Combine(_localAppDataDir, "models"));
            long settingsBytes = 0;
            string s1 = Path.Combine(_appDir, "user_settings.json");
            string s2 = Path.Combine(_localAppDataDir, "user_settings.json");
            if (File.Exists(s1)) try { settingsBytes += new FileInfo(s1).Length; } catch { }
            if (File.Exists(s2)) try { settingsBytes += new FileInfo(s2).Length; } catch { }

            Panel card = new Panel();
            card.BackColor = cardDark;
            card.Location = new Point(20, 16);
            card.Size = new Size(560, 314);
            card.Paint += delegate(object s, PaintEventArgs e)
            {
                using (Pen p = new Pen(borderCol, 1))
                {
                    e.Graphics.DrawRectangle(p, 0, 0, card.Width - 1, card.Height - 1);
                }
            };
            this.Controls.Add(card);

            Label lblTitle = new Label();
            lblTitle.Text = "SubVision AI — Kaldırma ve Bileşen Yöneticisi";
            lblTitle.Font = new Font("Segoe UI Semibold", 13F, FontStyle.Bold);
            lblTitle.ForeColor = textPrimary;
            lblTitle.Location = new Point(18, 14);
            lblTitle.AutoSize = true;
            card.Controls.Add(lblTitle);

            Label lblSub = new Label();
            lblSub.Text = "Uygulama ile birlikte indirilen bileşenlerden hangilerinin silineceğini opsiyonel olarak seçebilirsiniz:";
            lblSub.Font = new Font("Segoe UI", 8.5F, FontStyle.Regular);
            lblSub.ForeColor = textMuted;
            lblSub.Location = new Point(18, 42);
            lblSub.Size = new Size(524, 20);
            card.Controls.Add(lblSub);

            _chkCoreApp = new CheckBox();
            _chkCoreApp.Text = "1. Ana Uygulama Dosyaları, Masaüstü / Başlat Kısayolları ve Sistem Kaydı";
            _chkCoreApp.Checked = true;
            _chkCoreApp.ForeColor = textPrimary;
            _chkCoreApp.Font = new Font("Segoe UI Semibold", 9F, FontStyle.Bold);
            _chkCoreApp.Location = new Point(20, 74);
            _chkCoreApp.Size = new Size(520, 24);
            card.Controls.Add(_chkCoreApp);

            _chkRuntime = new CheckBox();
            _chkRuntime.Text = "2. İndirilen Python Çalışma Ortamı ve Yapay Zeka Paketleri (runtime/ — "
                             + SystemIntegrationHelper.FormatSizeMb(runtimeBytes) + ")";
            _chkRuntime.Checked = true;
            _chkRuntime.ForeColor = textPrimary;
            _chkRuntime.Location = new Point(20, 106);
            _chkRuntime.Size = new Size(520, 24);
            card.Controls.Add(_chkRuntime);

            _chkModels = new CheckBox();
            _chkModels.Text = "3. İndirilen Yapay Zeka Çeviri Modeli (models/opus-en-tr-ct2 — "
                            + SystemIntegrationHelper.FormatSizeMb(localModelsBytes) + ")";
            _chkModels.Checked = true;
            _chkModels.ForeColor = Color.FromArgb(250, 204, 21);
            _chkModels.Location = new Point(20, 138);
            _chkModels.Size = new Size(520, 24);
            card.Controls.Add(_chkModels);

            Label lblModelHint = new Label();
            lblModelHint.Text = "   (İpucu: İleride tekrar kurduğunuzda ~227 MB modeli yeniden indirmemek için işareti kaldırabilirsiniz)";
            lblModelHint.Font = new Font("Segoe UI", 7.8F, FontStyle.Regular);
            lblModelHint.ForeColor = textMuted;
            lblModelHint.Location = new Point(36, 162);
            lblModelHint.Size = new Size(510, 18);
            card.Controls.Add(lblModelHint);

            _chkSettings = new CheckBox();
            _chkSettings.Text = "4. Kişisel Kullanıcı Ayarları ve ROI Kalibrasyon Verileri (user_settings.json — "
                              + SystemIntegrationHelper.FormatSizeMb(settingsBytes) + ")";
            _chkSettings.Checked = true;
            _chkSettings.ForeColor = textPrimary;
            _chkSettings.Location = new Point(20, 188);
            _chkSettings.Size = new Size(520, 24);
            card.Controls.Add(_chkSettings);

            _chkCert = new CheckBox();
            _chkCert.Text = "5. Yayıncı Dijital İmza Sertifikasını (SubVision AI Open Source) Kullanıcı Deposundan Sil";
            _chkCert.Checked = false;
            _chkCert.ForeColor = textPrimary;
            _chkCert.Location = new Point(20, 220);
            _chkCert.Size = new Size(520, 24);
            card.Controls.Add(_chkCert);

            _lblStatus = new Label();
            _lblStatus.Text = "Konum: " + _appDir;
            _lblStatus.Font = new Font("Segoe UI", 8.25F, FontStyle.Regular);
            _lblStatus.ForeColor = textMuted;
            _lblStatus.Location = new Point(18, 256);
            _lblStatus.Size = new Size(524, 20);
            card.Controls.Add(_lblStatus);

            _progressBar = new FlatProgressBar();
            _progressBar.Location = new Point(18, 282);
            _progressBar.Size = new Size(524, 10);
            _progressBar.Value = 0;
            card.Controls.Add(_progressBar);

            _btnCleanSelectedOnly = SetupWizardForm.CreateFlatButton(
                "Sadece İndirilenleri Sıfırla",
                new Point(20, 344),
                new Size(185, 36),
                cardDark,
                amberCol,
                amberCol
            );
            _btnCleanSelectedOnly.Click += delegate { ExecuteCleanup(false); };
            this.Controls.Add(_btnCleanSelectedOnly);

            _btnFullUninstall = SetupWizardForm.CreateFlatButton(
                "Seçilileri Sil & Uygulamayı Kaldır",
                new Point(215, 344),
                new Size(245, 36),
                dangerCol,
                Color.White,
                dangerCol
            );
            _btnFullUninstall.Click += delegate { ExecuteCleanup(true); };
            this.Controls.Add(_btnFullUninstall);

            _btnClose = SetupWizardForm.CreateFlatButton(
                "Vazgeç",
                new Point(470, 344),
                new Size(110, 36),
                cardDark,
                textPrimary,
                borderCol
            );
            _btnClose.Click += delegate { this.Close(); };
            this.Controls.Add(_btnClose);
        }

        private static void SafeDeleteDir(string path)
        {
            if (string.IsNullOrEmpty(path) || !Directory.Exists(path)) return;
            try { Directory.Delete(path, true); } catch { }
        }

        private static void SafeDeleteFile(string path)
        {
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) return;
            try { File.Delete(path); } catch { }
        }

        private void ExecuteCleanup(bool fullUninstall)
        {
            if (!fullUninstall && !_chkRuntime.Checked && !_chkModels.Checked && !_chkSettings.Checked && !_chkCert.Checked)
            {
                MessageBox.Show(
                    "Lütfen sıfırlamak istediğiniz en az bir bileşeni (Python çalışma ortamı, Çeviri Modeli veya Ayarlar) işaretleyin.",
                    "SubVision AI",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information
                );
                return;
            }

            string confirmMsg = fullUninstall
                ? "Seçili bileşenler ve SubVision AI uygulaması bilgisayarınızdan kaldırılacak.\n\nDevam etmek istiyor musunuz?"
                : "Ana uygulama korunacak; yalnızca işaretlediğiniz indirilen bileşenler (Model / Runtime / Ayarlar) temizlenecek.\n\nDevam etmek istiyor musunuz?";

            DialogResult dr = MessageBox.Show(
                confirmMsg,
                "SubVision AI — Onay",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question
            );
            if (dr != DialogResult.Yes) return;

            _btnFullUninstall.Enabled = false;
            _btnCleanSelectedOnly.Enabled = false;
            _progressBar.FillColor = Color.FromArgb(220, 38, 38);
            _progressBar.Value = 15;

            // 1. Taşınabilir Python Runtime temizliği
            if (_chkRuntime.Checked)
            {
                _lblStatus.Text = "Taşınabilir Python çalışma ortamı (runtime/) siliniyor...";
                Application.DoEvents();
                SafeDeleteDir(Path.Combine(_appDir, "runtime"));
                SafeDeleteDir(Path.Combine(_appDir, "__pycache__"));
            }
            _progressBar.Value = 40;

            // 2. İndirilen Yapay Zeka Çeviri Modeli (~227 MB) temizliği
            if (_chkModels.Checked)
            {
                _lblStatus.Text = "İndirilen yapay zeka çeviri modeli (models/) siliniyor...";
                Application.DoEvents();
                SafeDeleteDir(Path.Combine(_appDir, "models"));
                SafeDeleteDir(Path.Combine(_localAppDataDir, "models"));
            }
            _progressBar.Value = 65;

            // 3. Kullanıcı ayarları ve ROI kalibrasyonu temizliği
            if (_chkSettings.Checked)
            {
                _lblStatus.Text = "Kullanıcı ayarları (user_settings.json) siliniyor...";
                Application.DoEvents();
                SafeDeleteFile(Path.Combine(_appDir, "user_settings.json"));
                SafeDeleteFile(Path.Combine(_localAppDataDir, "user_settings.json"));
                SafeDeleteFile(Path.Combine(_appDir, "benchmark_results.json"));
            }
            _progressBar.Value = 80;

            // 4. Yayıncı sertifikası temizliği
            if (_chkCert.Checked)
            {
                _lblStatus.Text = "Yayıncı sertifikası kullanıcı deposundan kaldırılıyor...";
                Application.DoEvents();
                SystemIntegrationHelper.RemovePublisherCertificateFromUserStore();
            }

            // 5. Tam kaldırma seçildiyse kısayollar, kayıt defteri ve ana dosyaları kaldır
            if (fullUninstall || _chkCoreApp.Checked && fullUninstall)
            {
                _lblStatus.Text = "Kısayollar ve sistem kayıtları kaldırılıyor...";
                Application.DoEvents();
                SystemIntegrationHelper.RemoveShortcutsAndRegistry();

                // Eğer geliştirici git deposu (.git) değilse çıkartılan uygulama dosyalarını temizle
                bool isGitRepo = Directory.Exists(Path.Combine(_appDir, ".git"));
                if (!isGitRepo)
                {
                    string[] appFiles = new string[]
                    {
                        "main.py", "hardware.py", "ocr_engine.py", "translator.py",
                        "overlay_ui.py", "glossary.py", "benchmark.py", "test_pipeline.py",
                        "requirements.txt", "baslat.bat", "setup_bootstrap.ps1"
                    };
                    for (int i = 0; i < appFiles.Length; i++)
                    {
                        SafeDeleteFile(Path.Combine(_appDir, appFiles[i]));
                    }
                    SafeDeleteDir(Path.Combine(_appDir, "assets"));
                    SafeDeleteDir(Path.Combine(_appDir, "__pycache__"));
                }
            }

            // Eğer %LOCALAPPDATA%\SubVisionAI boş kaldıysa klasörü de temizle
            try
            {
                if (Directory.Exists(_localAppDataDir) &&
                    Directory.GetFiles(_localAppDataDir, "*", SearchOption.AllDirectories).Length == 0)
                {
                    Directory.Delete(_localAppDataDir, true);
                }
            }
            catch { }

            _progressBar.FillColor = Color.FromArgb(16, 185, 129);
            _progressBar.Value = 100;
            _lblStatus.Text = fullUninstall
                ? "✓ Kaldırma işlemi başarıyla tamamlandı."
                : "✓ Seçili bileşenler başarıyla temizlendi.";

            MessageBox.Show(
                fullUninstall
                    ? "SubVision AI ve seçtiğiniz bileşenler bilgisayarınızdan başarıyla kaldırıldı."
                    : "Seçtiğiniz indirilen bileşenler başarıyla temizlendi.",
                "SubVision AI — Tamamlandı",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information
            );

            this.DialogResult = DialogResult.OK;
            this.Close();
        }
    }

    static class Program
    {
        private static string FindReadyPythonw(string appDir)
        {
            string venvPyw = Path.Combine(appDir, ".venv", "Scripts", "pythonw.exe");
            if (File.Exists(venvPyw)) return venvPyw;

            string runtimePyw = Path.Combine(appDir, "runtime", "pythonw.exe");
            string runtimeMarker = Path.Combine(appDir, "runtime", ".deps_installed");
            if (File.Exists(runtimePyw) && File.Exists(runtimeMarker)) return runtimePyw;

            return null;
        }

        private static void LaunchMainApp(string pythonwPath, string appDir, string mainPy)
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = pythonwPath;
            psi.Arguments = "\"" + mainPy + "\"";
            psi.WorkingDirectory = appDir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            Process.Start(psi);
        }

        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            string exeName = Path.GetFileName(Application.ExecutablePath) ?? "";

            bool isUninstallMode = exeName.IndexOf("Uninstall", StringComparison.OrdinalIgnoreCase) >= 0;
            bool isSetupMode = false;

            if (args != null)
            {
                for (int i = 0; i < args.Length; i++)
                {
                    string a = (args[i] ?? "").Trim().ToLowerInvariant();
                    if (a == "--uninstall" || a == "/uninstall" || a == "-u" || a == "--manage")
                    {
                        isUninstallMode = true;
                    }
                    else if (a == "--setup" || a == "/setup")
                    {
                        isSetupMode = true;
                    }
                }
            }

            if (isUninstallMode)
            {
                using (UninstallWizardForm uninst = new UninstallWizardForm(appDir))
                {
                    uninst.ShowDialog();
                }
                return;
            }

            string mainPy = Path.Combine(appDir, "main.py");
            string readyPyw = FindReadyPythonw(appDir);

            // Eğer zaten kuruluysa doğrudan uygulamayı başlat (arka planda hiçbir dosya yazma!)
            if (!isSetupMode && readyPyw != null && File.Exists(mainPy))
            {
                LaunchMainApp(readyPyw, appDir, mainPy);
                return;
            }

            // Kurulu değilse kullanıcıya interaktif Kurulum Yardımcısını göster
            using (SetupWizardForm wizard = new SetupWizardForm(appDir))
            {
                DialogResult res = wizard.ShowDialog();
                if (res == DialogResult.OK && wizard.SetupSucceeded)
                {
                    string newPyw = FindReadyPythonw(appDir);
                    if (newPyw != null && File.Exists(mainPy))
                    {
                        LaunchMainApp(newPyw, appDir, mainPy);
                    }
                }
            }
        }
    }
}
"""


def ensure_publisher_certificate_and_sign(base_dir: str, exe_paths: List[str]) -> bool:
    """
    Windows üzerinde üretilen tüm .exe dosyalarını Authenticode SHA-256 + RFC 3161 Timestamp ile imzalar.
    - SUBVISION_CERT_PFX ve SUBVISION_CERT_PASS ortam değişkenleri tanımlıysa harici PFX sertifikasını kullanır.
    - Tanımlı değilse CurrentUser\\My deposunda 'CN=SubVision AI Open Source' RSA-3072 SHA-256 kod imzalama
      sertifikasını oluşturur/kullanır ve açık sertifikayı 'assets/SubVisionAI-Publisher.cer' olarak dışa aktarır.
    """
    if os.name != "nt":
        return False

    valid_targets = [os.path.abspath(p) for p in exe_paths if p and os.path.exists(p)]
    if not valid_targets:
        return False

    cer_out = os.path.join(base_dir, "assets", "SubVisionAI-Publisher.cer")
    os.makedirs(os.path.dirname(cer_out), exist_ok=True)
    targets_ps_array = ",".join(f"'{p.replace(chr(39), chr(39)*2)}'" for p in valid_targets)
    cer_out_escaped = cer_out.replace("'", "''")

    ps_script = f"""
$ErrorActionPreference = 'Stop'
$pfxPath = $env:SUBVISION_CERT_PFX
$pfxPass = $env:SUBVISION_CERT_PASS
$cert = $null

if ($pfxPath -and (Test-Path $pfxPath)) {{
    $secPass = ConvertTo-SecureString -String $pfxPass -AsPlainText -Force
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($pfxPath, $secPass)
}} else {{
    $cert = Get-ChildItem Cert:\\CurrentUser\\My -CodeSigningCert -ErrorAction SilentlyContinue |
        Where-Object {{ $_.Subject -like '*SubVision AI Open Source*' -and $_.NotAfter -gt (Get-Date).AddDays(30) }} |
        Select-Object -First 1

    if (-not $cert) {{
        $cert = New-SelfSignedCertificate `
            -Type CodeSigningCert `
            -Subject 'CN=SubVision AI Open Source, O=Andac Basaran, C=TR' `
            -KeyAlgorithm RSA `
            -KeyLength 3072 `
            -HashAlgorithm SHA256 `
            -CertStoreLocation 'Cert:\\CurrentUser\\My' `
            -NotAfter (Get-Date).AddYears(5) `
            -TextExtension @('2.5.29.37={{text}}1.3.6.1.5.5.7.3.3')
    }}

    # Yerel geliştirici/kullanıcı makinesinde TrustedPublisher ve TrustedPeople depolarına kaydet (sessiz, onay penceresi açmaz)
    foreach ($storeName in @('TrustedPublisher', 'TrustedPeople')) {{
        try {{
            $store = New-Object System.Security.Cryptography.X509Certificates.X509Store($storeName, 'CurrentUser')
            $store.Open('ReadWrite')
            $found = $store.Certificates.Find('FindByThumbprint', $cert.Thumbprint, $false)
            if (-not $found -or $found.Count -eq 0) {{
                $store.Add($cert)
            }}
            $store.Close()
        }} catch {{}}
    }}
}}

if ($cert) {{
    Export-Certificate -Cert $cert -FilePath '{cer_out_escaped}' -Force | Out-Null
    $targets = @({targets_ps_array})
    foreach ($exe in $targets) {{
        if (Test-Path $exe) {{
            $sig = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert -HashAlgorithm SHA256 -TimestampServer 'http://timestamp.digicert.com' -ErrorAction SilentlyContinue
            if (-not $sig -or $sig.Status -eq 'NotSigned') {{
                $sig = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert -HashAlgorithm SHA256
            }}
            Write-Host "[İMZALANDI] $([System.IO.Path]::GetFileName($exe)) -> Durum: $($sig.Status) | Thumbprint: $($cert.Thumbprint)"
        }}
    }}
}}
"""
    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if res.stdout.strip():
            print(res.stdout.strip())
        if res.returncode != 0 and res.stderr.strip():
            print(f"[BİLGİ] İmzalama uyarısı: {res.stderr.strip()}")
            return False
        return True
    except Exception as exc:
        print(f"[BİLGİ] Dijital imzalama atlandı: {exc}")
        return False


def build_native_exe(base_dir: str) -> bool:
    csc_candidates = [
        r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
    ]
    csc_path = next((p for p in csc_candidates if os.path.exists(p)), None)
    if not csc_path:
        print("[!] Microsoft .NET Framework csc.exe bulunamadı (yalnızca Windows üzerinde derlenebilir).")
        return False

    # Önce yayıncı sertifikasının (assets/SubVisionAI-Publisher.cer) mevcut olduğundan emin ol
    cer_file = os.path.join(base_dir, "assets", "SubVisionAI-Publisher.cer")
    if not os.path.exists(cer_file):
        ensure_publisher_certificate_and_sign(base_dir, [])

    cs_file = os.path.join(base_dir, "_launcher_tmp.cs")
    manifest_file = os.path.join(base_dir, "_launcher_tmp.manifest")
    exe_file = os.path.join(base_dir, "SubVisionAI.exe")
    uninstaller_file = os.path.join(base_dir, "SubVisionAI-Uninstaller.exe")
    ico_file = os.path.join(base_dir, "assets", "app_icon.ico")

    with open(cs_file, "w", encoding="utf-8-sig") as f:
        f.write(LauncherCSharpSource.strip())
    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write(AppManifestXml.strip())

    cmd = [
        csc_path,
        "/nologo",
        "/target:winexe",
        "/optimize+",
        "/platform:x64",
        f"/win32manifest:{manifest_file}",
        "/reference:System.Windows.Forms.dll",
        "/reference:System.Drawing.dll",
        "/reference:System.IO.Compression.dll",
        "/reference:System.IO.Compression.FileSystem.dll",
        f"/out:{exe_file}",
    ]
    if os.path.exists(ico_file):
        cmd.append(f"/win32icon:{ico_file}")

    embedded_list = list(EMBEDDED_FILES)
    if os.path.exists(cer_file):
        embedded_list.append(("assets/SubVisionAI-Publisher.cer", "assets/SubVisionAI-Publisher.cer"))

    for rel_src, _ in embedded_list:
        abs_src = os.path.join(base_dir, rel_src.replace("/", os.sep))
        res_id = "res_" + os.path.basename(rel_src)
        if os.path.exists(abs_src):
            cmd.append(f"/resource:{abs_src},{res_id}")

    cmd.append(cs_file)

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if res.returncode == 0 and os.path.exists(exe_file):
            # Kaldırma yardımcısını (SubVisionAI-Uninstaller.exe) da kök dizine üret
            try:
                import shutil

                shutil.copy2(exe_file, uninstaller_file)
            except Exception:
                pass

            # Her iki .exe dosyasını Authenticode SHA-256 + DigiCert Timestamp ile imzala
            ensure_publisher_certificate_and_sign(base_dir, [exe_file, uninstaller_file])

            size_kb = os.path.getsize(exe_file) / 1024.0
            print(
                f"[OK] Dijital İmzalı Kurulum Yardımcısı & Uninstaller üretildi: "
                f"SubVisionAI.exe & SubVisionAI-Uninstaller.exe ({size_kb:.1f} KB)"
            )
            return True
        print(f"[HATA] Derleme başarısız:\n{res.stdout}\n{res.stderr}")
        return False
    finally:
        for tmp_path in (cs_file, manifest_file):
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


def build_pyinstaller_bundle(base_dir: str) -> None:
    print("[*] PyInstaller bağımsız (standalone --onedir) paket derlemesi başlatılıyor...")
    ico_file = os.path.join(base_dir, "assets", "app_icon.ico")
    png_file = os.path.join(base_dir, "assets", "app_icon.png")
    uninstaller_file = os.path.join(base_dir, "SubVisionAI-Uninstaller.exe")
    data_sep = ";" if os.name == "nt" else ":"

    if not os.path.exists(uninstaller_file):
        build_native_exe(base_dir)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
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
        "--collect-all",
        "sentencepiece",
    ]
    if os.path.exists(ico_file):
        cmd.extend(["--icon", ico_file, "--add-data", f"{ico_file}{data_sep}assets"])
    if os.path.exists(png_file):
        cmd.extend(["--add-data", f"{png_file}{data_sep}assets"])

    cmd.append(os.path.join(base_dir, "main.py"))
    subprocess.run(cmd, cwd=base_dir, check=True)

    dist_app_dir = os.path.join(base_dir, "dist", "SubVisionAI")
    dist_exe = os.path.join(dist_app_dir, "SubVisionAI.exe")
    dist_uninst = os.path.join(dist_app_dir, "SubVisionAI-Uninstaller.exe")
    if os.path.exists(uninstaller_file) and os.path.exists(dist_app_dir):
        import shutil

        shutil.copy2(uninstaller_file, dist_uninst)

    ensure_publisher_certificate_and_sign(base_dir, [dist_exe, dist_uninst])
    print("[OK] PyInstaller standalone paketi 'dist/SubVisionAI' klasörüne çıkartıldı ve imzalandı.")


if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    if "--sign" in sys.argv:
        targets = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
        ensure_publisher_certificate_and_sign(root, targets)
    elif "--only-pyinstaller" in sys.argv:
        build_pyinstaller_bundle(root)
    else:
        build_native_exe(root)
        if "--pyinstaller" in sys.argv:
            build_pyinstaller_bundle(root)
