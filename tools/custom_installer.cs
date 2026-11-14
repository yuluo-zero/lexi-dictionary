using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

namespace LexiSetup
{
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            bool silent = false;
            bool noDesktop = false;
            string dir = null;
            foreach (string a in args)
            {
                if (a.Equals("/S", StringComparison.OrdinalIgnoreCase)) silent = true;
                else if (a.Equals("/NODESKTOP", StringComparison.OrdinalIgnoreCase)) noDesktop = true;
                else if (a.StartsWith("/DIR=", StringComparison.OrdinalIgnoreCase)) dir = a.Substring(5).Trim('"');
            }
            if (string.IsNullOrWhiteSpace(dir))
                dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "LexiDictionary");

            if (silent)
            {
                try
                {
                    Installer.Extract(dir, noDesktop, null);
                    Environment.Exit(0);
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.Message, "划词词典 安装失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    Environment.Exit(1);
                }
                return;
            }
            Application.Run(new SetupForm(dir, noDesktop));
        }
    }

    internal sealed class SetupForm : Form
    {
        private readonly TextBox _dir;
        private readonly CheckBox _desktop;
        private readonly Button _install;
        private readonly ProgressBar _bar;
        private readonly Label _status;
        private readonly bool _noDesktop;

        public SetupForm(string dir, bool noDesktop)
        {
            _noDesktop = noDesktop;
            Text = "划词词典 安装程序";
            ClientSize = new Size(560, 265);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft YaHei UI", 9F);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            Label title = new Label();
            title.Text = "划词词典";
            title.Font = new Font("Microsoft YaHei UI", 18F, FontStyle.Bold);
            title.AutoSize = true;
            title.Location = new Point(24, 20);
            Controls.Add(title);

            Label sub = new Label();
            sub.Text = "安装到当前用户，不需要管理员权限";
            sub.ForeColor = Color.DimGray;
            sub.AutoSize = true;
            sub.Location = new Point(27, 62);
            Controls.Add(sub);

            Label l = new Label();
            l.Text = "安装位置";
            l.AutoSize = true;
            l.Location = new Point(27, 105);
            Controls.Add(l);

            _dir = new TextBox();
            _dir.Text = dir;
            _dir.Location = new Point(100, 102);
            _dir.Width = 350;
            Controls.Add(_dir);

            Button browse = new Button();
            browse.Text = "浏览...";
            browse.Location = new Point(458, 100);
            browse.Width = 78;
            browse.Click += delegate
            {
                using (FolderBrowserDialog f = new FolderBrowserDialog())
                {
                    f.SelectedPath = _dir.Text;
                    if (f.ShowDialog(this) == DialogResult.OK) _dir.Text = f.SelectedPath;
                }
            };
            Controls.Add(browse);

            _desktop = new CheckBox();
            _desktop.Text = "创建桌面快捷方式";
            _desktop.Checked = !_noDesktop;
            _desktop.AutoSize = true;
            _desktop.Location = new Point(100, 140);
            Controls.Add(_desktop);

            _bar = new ProgressBar();
            _bar.Location = new Point(100, 170);
            _bar.Width = 436;
            _bar.Height = 18;
            Controls.Add(_bar);

            _status = new Label();
            _status.Text = "准备安装";
            _status.ForeColor = Color.DimGray;
            _status.AutoSize = true;
            _status.Location = new Point(100, 194);
            Controls.Add(_status);

            _install = new Button();
            _install.Text = "安装";
            _install.Location = new Point(356, 220);
            _install.Width = 88;
            _install.Height = 30;
            _install.Click += delegate { StartInstall(); };
            Controls.Add(_install);

            Button cancel = new Button();
            cancel.Text = "取消";
            cancel.Location = new Point(450, 220);
            cancel.Width = 86;
            cancel.Height = 30;
            cancel.Click += delegate { Close(); };
            Controls.Add(cancel);
        }

        private void StartInstall()
        {
            string dest = _dir.Text.Trim();
            if (dest.Length == 0) return;
            _install.Enabled = false;
            _bar.Style = ProgressBarStyle.Marquee;
            _status.Text = "正在安装...";
            BackgroundWorker bw = new BackgroundWorker();
            bw.DoWork += delegate(object s, DoWorkEventArgs e)
            {
                Installer.Extract(dest, !_desktop.Checked, delegate(string msg)
                {
                    try { BeginInvoke(new Action(delegate { _status.Text = msg; })); } catch { }
                });
            };
            bw.RunWorkerCompleted += delegate(object s, RunWorkerCompletedEventArgs e)
            {
                _bar.Style = ProgressBarStyle.Blocks;
                _bar.Value = 100;
                if (e.Error != null)
                {
                    _install.Enabled = true;
                    _status.Text = "安装失败";
                    MessageBox.Show(this, e.Error.Message, "安装失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                _status.Text = "安装完成";
                DialogResult r = MessageBox.Show(this, "安装完成。现在启动划词词典？", "划词词典",
                    MessageBoxButtons.YesNo, MessageBoxIcon.Information);
                if (r == DialogResult.Yes)
                {
                    try { System.Diagnostics.Process.Start(Path.Combine(dest, "LexiDictionary.exe")); } catch { }
                }
                Close();
            };
            bw.RunWorkerAsync();
        }
    }

    internal static class Installer
    {
        public static void Extract(string dest, bool noDesktop, Action<string> progress)
        {
            dest = Path.GetFullPath(dest);
            Directory.CreateDirectory(dest);
            Assembly asm = Assembly.GetExecutingAssembly();
            using (Stream zs = asm.GetManifestResourceStream("payload.zip"))
            {
                if (zs == null) throw new Exception("安装包数据损坏。");
                using (ZipArchive zip = new ZipArchive(zs, ZipArchiveMode.Read))
                {
                    foreach (ZipArchiveEntry e in zip.Entries)
                    {
                        string rel = e.FullName.Replace('/', Path.DirectorySeparatorChar);
                        if (rel.EndsWith(Path.DirectorySeparatorChar.ToString())) continue;
                        // 升级时绝不覆盖用户数据
                        if (rel.Equals(@"data\user.db", StringComparison.OrdinalIgnoreCase) ||
                            rel.Equals(@"data\user.db.bak", StringComparison.OrdinalIgnoreCase) ||
                            rel.Equals(@"data\settings.json", StringComparison.OrdinalIgnoreCase))
                        {
                            string existing = Path.Combine(dest, rel);
                            if (File.Exists(existing)) continue;
                        }
                        string outPath = Path.GetFullPath(Path.Combine(dest, rel));
                        if (!outPath.StartsWith(dest, StringComparison.OrdinalIgnoreCase)) continue;
                        string parent = Path.GetDirectoryName(outPath);
                        if (!string.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);
                        if (File.Exists(outPath)) File.Delete(outPath);
                        using (Stream input = e.Open())
                        using (FileStream output = File.Create(outPath))
                            input.CopyTo(output);
                        if (progress != null) progress(rel);
                    }
                }
            }
            try { MakeShortcuts(dest, noDesktop); } catch { }
            try { WriteUninstaller(dest); } catch { }
            try { RegisterUninstall(dest); } catch { }
        }

        private static object NewShell()
        {
            Type t = Type.GetTypeFromProgID("WScript.Shell");
            return Activator.CreateInstance(t);
        }

        private static void MakeShortcut(string path, string target, string workdir, string icon)
        {
            object shell = NewShell();
            object lnk = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
            lnk.GetType().InvokeMember("TargetPath", BindingFlags.SetProperty, null, lnk, new object[] { target });
            lnk.GetType().InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, lnk, new object[] { workdir });
            lnk.GetType().InvokeMember("IconLocation", BindingFlags.SetProperty, null, lnk, new object[] { icon });
            lnk.GetType().InvokeMember("Save", BindingFlags.InvokeMethod, null, lnk, null);
        }

        private static string ShortcutName(string dir)
        {
            // 不覆盖已有的 D:\划词词典 快捷方式
            string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            string candidate = Path.Combine(desktop, "划词词典.lnk");
            if (!File.Exists(candidate)) return "划词词典";
            try
            {
                object shell = NewShell();
                object lnk = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { candidate });
                string target = (string)lnk.GetType().InvokeMember("TargetPath", BindingFlags.GetProperty, null, lnk, null);
                if (target.StartsWith(dir, StringComparison.OrdinalIgnoreCase)) return "划词词典";
            }
            catch { }
            return "划词词典（安装版）";
        }

        private static void MakeShortcuts(string dir, bool noDesktop)
        {
            string exe = Path.Combine(dir, "LexiDictionary.exe");
            string icon = Path.Combine(dir, "app", "assets", "app.ico") + ",0";
            string name = ShortcutName(dir);

            string startDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs", "划词词典");
            try
            {
                Directory.CreateDirectory(startDir);
                MakeShortcut(Path.Combine(startDir, name + ".lnk"), exe, dir, icon);
            }
            catch { }

            if (!noDesktop)
            {
                try
                {
                    string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                    MakeShortcut(Path.Combine(desktop, name + ".lnk"), exe, dir, icon);
                }
                catch { }
            }
        }

        private static void WriteUninstaller(string dir)
        {
            string cmd =
                "@echo off\r\n" +
                "taskkill /f /im LexiDictionary.exe >nul 2>&1\r\n" +
                "rmdir /s /q \"%~dp0app\" 2>nul\r\n" +
                "rmdir /s /q \"%~dp0runtime\" 2>nul\r\n" +
                "del \"%~dp0main.py\" 2>nul\r\n" +
                "del \"%~dp0LexiDictionary.exe\" 2>nul\r\n" +
                "del \"%~dp0start.cmd\" 2>nul\r\n" +
                "del \"%~dp0start.vbs\" 2>nul\r\n" +
                "del \"%~dp0uninstall.cmd\" 2>nul\r\n" +
                "echo 已卸载。data 文件夹保留，可手动删除。\r\n" +
                "pause\r\n";
            File.WriteAllText(Path.Combine(dir, "uninstall.cmd"), cmd, System.Text.Encoding.Default);
        }

        private static void RegisterUninstall(string dir)
        {
            using (RegistryKey k = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\LexiDictionary"))
            {
                if (k == null) return;
                k.SetValue("DisplayName", "划词词典");
                k.SetValue("DisplayVersion", "1.2.4");
                k.SetValue("Publisher", "雨落降零度");
                k.SetValue("InstallLocation", dir);
                k.SetValue("DisplayIcon", Path.Combine(dir, "LexiDictionary.exe"));
                k.SetValue("UninstallString", "cmd /c \"" + Path.Combine(dir, "uninstall.cmd") + "\"");
                k.SetValue("NoModify", 1, RegistryValueKind.DWord);
                k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            }
        }
    }
}
