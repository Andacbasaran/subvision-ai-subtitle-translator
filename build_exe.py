"""
SubVision AI — Windows Çalıştırılabilir (.exe) & Standalone Paket Derleme Aracı (v1.3)

İki dağıtım seçeneğini de üretir:
1. Varsayılan (`python build_exe.py`):
   - PowerShell / .bat / silent temp-dropper KULLANMAYAN, tamamen yerel C# WinForms
     flat koyu temalı GUI Kurulum Sihirbazı (`SubVisionAI.exe`) üretir.
   - Tam Win32 AssemblyInfo metadata ve Application Manifest (`asInvoker`, Win10/11, DPI)
     gömerek Windows Defender heuristic (TrojanDownloader) yanlış pozitiflerini ortadan kaldırır.
   - İlk açılışta siyah terminal penceresi açmadan taşınabilir Python 3.11 + bağımlılıkları
     ilerleme çubuğu ile kurar ve sonraki açılışlarda uygulamayı doğrudan başlatır.

2. Standalone (`python build_exe.py --pyinstaller` veya `--only-pyinstaller`):
   - PyInstaller `--onedir` ile Python kurulumu gerektirmeyen bağımsız `dist/SubVisionAI/`
     paketini oluşturur (Inno Setup `installer.iss` ve taşınabilir `.zip` için kaynak).
"""

import os
import subprocess
import sys

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
    processorArchitecture="*"
    name="SubVisionAI.Launcher"
    type="win32"
  />
  <description>SubVision AI Real-Time Subtitle Studio</description>
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

# NOT: Windows .NET Framework 4.x csc.exe C# 5.0 derleyicisidir.
# Uyumluluk için yalnızca C# 5.0 sözdizimi kullanılır (string interpolation / ?. yok).
LauncherCSharpSource = r"""
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("SubVision AI — Real-Time Subtitle Studio")]
[assembly: AssemblyDescription("Offline AI On-Screen Subtitle Translator Launcher & Setup Wizard")]
[assembly: AssemblyConfiguration("")]
[assembly: AssemblyCompany("SubVision AI Open Source")]
[assembly: AssemblyProduct("SubVision AI")]
[assembly: AssemblyCopyright("Copyright (c) 2026 SubVision AI Contributors (MIT License)")]
[assembly: AssemblyTrademark("")]
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

    internal sealed class SetupWizardForm : Form
    {
        private const string PythonEmbedUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip";
        private const string GetPipUrl = "https://bootstrap.pypa.io/get-pip.py";
        private const string VcRedistDocsUrl = "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist";

        private readonly string _appDir;
        private readonly string _runtimeDir;

        private Label _lblTitle;
        private Label _lblSubtitle;
        private Label _lblStep;
        private Label _lblPercent;
        private FlatProgressBar _progressBar;
        private Label _lblDetail;
        private Button _btnToggleLog;
        private Button _btnRetry;
        private Button _btnCancel;
        private TextBox _txtLog;

        private bool _logExpanded;
        private volatile bool _cancelRequested;
        private Thread _workerThread;
        private WebClient _activeWebClient;
        private Process _activeProcess;
        private readonly object _syncLock = new object();

        public bool SetupSucceeded { get; private set; }

        public SetupWizardForm(string appDir)
        {
            _appDir = appDir;
            _runtimeDir = Path.Combine(appDir, "runtime");
            _logExpanded = false;
            _cancelRequested = false;
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
            Color accent = Color.FromArgb(59, 130, 246);

            this.Text = "SubVision AI — Kurulum Sihirbazı";
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = true;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = bgDark;
            this.ForeColor = textPrimary;
            this.Font = new Font("Segoe UI", 9.5F, FontStyle.Regular);
            this.ClientSize = new Size(540, 250);

            string iconPath = Path.Combine(_appDir, "assets", "app_icon.ico");
            if (File.Exists(iconPath))
            {
                try { this.Icon = new Icon(iconPath); } catch { }
            }

            Panel headerCard = new Panel();
            headerCard.BackColor = cardDark;
            headerCard.Location = new Point(20, 18);
            headerCard.Size = new Size(500, 168);
            headerCard.Paint += delegate(object s, PaintEventArgs e)
            {
                using (Pen p = new Pen(borderCol, 1))
                {
                    e.Graphics.DrawRectangle(p, 0, 0, headerCard.Width - 1, headerCard.Height - 1);
                }
            };
            this.Controls.Add(headerCard);

            _lblTitle = new Label();
            _lblTitle.Text = "SubVision AI  v1.3";
            _lblTitle.Font = new Font("Segoe UI Semibold", 13.5F, FontStyle.Bold);
            _lblTitle.ForeColor = textPrimary;
            _lblTitle.Location = new Point(18, 16);
            _lblTitle.AutoSize = true;
            headerCard.Controls.Add(_lblTitle);

            _lblSubtitle = new Label();
            _lblSubtitle.Text = "İlk kurulum yapılıyor — yalnızca bir kez çalışır, siyah terminal açmaz.";
            _lblSubtitle.Font = new Font("Segoe UI", 8.75F, FontStyle.Regular);
            _lblSubtitle.ForeColor = textMuted;
            _lblSubtitle.Location = new Point(18, 44);
            _lblSubtitle.Size = new Size(464, 20);
            headerCard.Controls.Add(_lblSubtitle);

            _lblStep = new Label();
            _lblStep.Text = "Kurulum ortamı hazırlanıyor...";
            _lblStep.Font = new Font("Segoe UI Semibold", 9.5F, FontStyle.Bold);
            _lblStep.ForeColor = Color.FromArgb(226, 232, 240);
            _lblStep.Location = new Point(18, 82);
            _lblStep.Size = new Size(400, 22);
            headerCard.Controls.Add(_lblStep);

            _lblPercent = new Label();
            _lblPercent.Text = "0%";
            _lblPercent.Font = new Font("Segoe UI Semibold", 9.5F, FontStyle.Bold);
            _lblPercent.ForeColor = accent;
            _lblPercent.TextAlign = ContentAlignment.MiddleRight;
            _lblPercent.Location = new Point(422, 82);
            _lblPercent.Size = new Size(60, 22);
            headerCard.Controls.Add(_lblPercent);

            _progressBar = new FlatProgressBar();
            _progressBar.Location = new Point(18, 110);
            _progressBar.Size = new Size(464, 12);
            headerCard.Controls.Add(_progressBar);

            _lblDetail = new Label();
            _lblDetail.Text = "Resmi Python ve yapay zeka paketleri indirilecek.";
            _lblDetail.Font = new Font("Segoe UI", 8.5F, FontStyle.Regular);
            _lblDetail.ForeColor = textMuted;
            _lblDetail.Location = new Point(18, 132);
            _lblDetail.Size = new Size(464, 22);
            headerCard.Controls.Add(_lblDetail);

            _btnToggleLog = CreateFlatButton("Detayları Göster", new Point(20, 200), new Size(138, 32), cardDark, textMuted, borderCol);
            _btnToggleLog.Click += delegate { ToggleLogPanel(); };
            this.Controls.Add(_btnToggleLog);

            _btnRetry = CreateFlatButton("Tekrar Dene", new Point(292, 200), new Size(110, 32), accent, Color.White, accent);
            _btnRetry.Visible = false;
            _btnRetry.Click += delegate { StartSetupAsync(); };
            this.Controls.Add(_btnRetry);

            _btnCancel = CreateFlatButton("İptal", new Point(410, 200), new Size(110, 32), cardDark, textPrimary, borderCol);
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
            _txtLog.Location = new Point(20, 246);
            _txtLog.Size = new Size(500, 150);
            _txtLog.Visible = false;
            this.Controls.Add(_txtLog);

            this.Shown += delegate
            {
                CheckVcRedistWarning();
                StartSetupAsync();
            };

            this.FormClosing += delegate(object sender, FormClosingEventArgs e)
            {
                if (_workerThread != null && _workerThread.IsAlive && !SetupSucceeded)
                {
                    _cancelRequested = true;
                    AbortActiveOperations();
                }
            };
        }

        private static Button CreateFlatButton(string text, Point loc, Size size, Color bg, Color fg, Color border)
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

        private void ToggleLogPanel()
        {
            _logExpanded = !_logExpanded;
            _txtLog.Visible = _logExpanded;
            _btnToggleLog.Text = _logExpanded ? "Detayları Gizle" : "Detayları Göster";
            this.ClientSize = _logExpanded ? new Size(540, 412) : new Size(540, 250);
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
            catch
            {
                // Kontrol hatası kurulumu engellemesin.
            }
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
            _cancelRequested = false;
            _btnRetry.Visible = false;
            _btnCancel.Text = "İptal";
            _progressBar.FillColor = Color.FromArgb(59, 130, 246);
            UpdateProgress("Kurulum başlatılıyor...", 2, "Dosyalar doğrulanıyor...");

            _workerThread = new Thread(RunSetupPipeline);
            _workerThread.IsBackground = true;
            _workerThread.Start();
        }

        private void RequestCancelAndClose()
        {
            if (_workerThread != null && _workerThread.IsAlive)
            {
                _cancelRequested = true;
                AbortActiveOperations();
            }
            this.DialogResult = DialogResult.Cancel;
            this.Close();
        }

        private void AbortActiveOperations()
        {
            lock (_syncLock)
            {
                if (_activeWebClient != null)
                {
                    try { _activeWebClient.CancelAsync(); } catch { }
                }
                if (_activeProcess != null)
                {
                    try
                    {
                        if (!_activeProcess.HasExited)
                        {
                            _activeProcess.Kill();
                        }
                    }
                    catch { }
                }
            }
        }

        private void DownloadFileWithProgress(string url, string destPath, int basePct, int spanPct, string stepLabel)
        {
            ManualResetEvent done = new ManualResetEvent(false);
            Exception downloadError = null;

            using (WebClient wc = new WebClient())
            {
                wc.Headers.Add("User-Agent", "SubVisionAI-Setup/1.3");
                lock (_syncLock) { _activeWebClient = wc; }

                wc.DownloadProgressChanged += delegate(object sender, DownloadProgressChangedEventArgs e)
                {
                    int pct = basePct + (int)Math.Round(spanPct * (e.ProgressPercentage / 100.0));
                    double recvMb = e.BytesReceived / (1024.0 * 1024.0);
                    double totMb = e.TotalBytesToReceive > 0 ? e.TotalBytesToReceive / (1024.0 * 1024.0) : 0.0;
                    string info = totMb > 0
                        ? string.Format("İndiriliyor: {0:F1} MB / {1:F1} MB", recvMb, totMb)
                        : string.Format("İndiriliyor: {0:F1} MB", recvMb);
                    UpdateProgress(stepLabel, pct, info);
                };

                wc.DownloadFileCompleted += delegate(object sender, AsyncCompletedEventArgs e)
                {
                    if (e.Cancelled)
                    {
                        downloadError = new OperationCanceledException("Kurulum kullanıcı tarafından iptal edildi.");
                    }
                    else if (e.Error != null)
                    {
                        downloadError = e.Error;
                    }
                    done.Set();
                };

                AppendLog(">> İndiriliyor: " + url);
                wc.DownloadFileAsync(new Uri(url), destPath);
                done.WaitOne();

                lock (_syncLock) { _activeWebClient = null; }
            }

            if (downloadError != null)
            {
                if (File.Exists(destPath))
                {
                    try { File.Delete(destPath); } catch { }
                }
                throw downloadError;
            }
        }

        private int RunHiddenProcess(string fileName, string arguments, string workingDir, Action<string> onOutputLine)
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
                lock (_syncLock) { _activeProcess = proc; }

                proc.BeginOutputReadLine();
                proc.BeginErrorReadLine();
                proc.WaitForExit();

                lock (_syncLock) { _activeProcess = null; }
                return proc.ExitCode;
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

        private void RunSetupPipeline()
        {
            try
            {
                // TLS 1.2 (3072) garanti edilir
                ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;

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
                    DownloadFileWithProgress(
                        PythonEmbedUrl,
                        pyZip,
                        5,
                        25,
                        "[1/3] Taşınabilir Python 3.11.9 indiriliyor..."
                    );

                    if (_cancelRequested) throw new OperationCanceledException();
                    UpdateProgress("[1/3] Python dosyaları çıkartılıyor...", 32, "Arşiv açılıyor...");
                    AppendLog(">> Python arşivi çıkartılıyor...");
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
                    DownloadFileWithProgress(
                        GetPipUrl,
                        getPipPy,
                        35,
                        10,
                        "[2/3] Paket yöneticisi (pip) indiriliyor..."
                    );

                    if (_cancelRequested) throw new OperationCanceledException();
                    UpdateProgress("[2/3] Paket yöneticisi (pip) kuruluyor...", 48, "Arka planda kuruluyor...");
                    int rcPip = RunHiddenProcess(pyExe, "\"" + getPipPy + "\" --no-warn-script-location", _appDir, null);
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
                int rcDeps = RunHiddenProcess(
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
                SetupSucceeded = true;

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
                AppendLog("[İPTAL] Kurulum kullanıcı tarafından iptal edildi.");
            }
            catch (Exception ex)
            {
                AppendLog("[HATA] " + ex.Message);
                SafeUi(delegate
                {
                    _progressBar.FillColor = Color.FromArgb(239, 68, 68);
                    _lblPercent.ForeColor = Color.FromArgb(239, 68, 68);
                    _lblStep.Text = "Kurulum tamamlanamadı.";
                    _lblDetail.Text = ex.Message;
                    _btnRetry.Visible = true;
                    _btnCancel.Text = "Kapat";
                    EnsureLogExpanded();
                });
            }
        }
    }

    static class Program
    {
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
            { "res_app_icon.png", "assets\\app_icon.png" }
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
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            EnsurePayloadExtracted(appDir);

            string mainPy = Path.Combine(appDir, "main.py");
            string readyPyw = FindReadyPythonw(appDir);

            if (readyPyw != null && File.Exists(mainPy))
            {
                LaunchMainApp(readyPyw, appDir, mainPy);
                return;
            }

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


def build_native_exe(base_dir: str) -> bool:
    csc_candidates = [
        r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
    ]
    csc_path = next((p for p in csc_candidates if os.path.exists(p)), None)
    if not csc_path:
        print("[!] Microsoft .NET Framework csc.exe bulunamadı (yalnızca Windows üzerinde derlenebilir).")
        return False

    cs_file = os.path.join(base_dir, "_launcher_tmp.cs")
    manifest_file = os.path.join(base_dir, "_launcher_tmp.manifest")
    exe_file = os.path.join(base_dir, "SubVisionAI.exe")
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
        "/platform:anycpu",
        f"/win32manifest:{manifest_file}",
        "/reference:System.Windows.Forms.dll",
        "/reference:System.Drawing.dll",
        "/reference:System.IO.Compression.dll",
        "/reference:System.IO.Compression.FileSystem.dll",
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
                f"[OK] PowerShell'siz GUI Kurulum Sihirbazlı Windows .exe üretildi: {exe_file} ({size_kb:.1f} KB)"
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
    data_sep = ";" if os.name == "nt" else ":"

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
    print("[OK] PyInstaller standalone paketi 'dist/SubVisionAI' klasörüne çıkartıldı.")


if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    if "--only-pyinstaller" in sys.argv:
        build_pyinstaller_bundle(root)
    else:
        build_native_exe(root)
        if "--pyinstaller" in sys.argv:
            build_pyinstaller_bundle(root)
