#include <windows.h>
#include <wchar.h>

static void show_error(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"划词词典", MB_ICONERROR | MB_OK);
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR cmdLine, int show) {
    (void)hInst; (void)hPrev; (void)cmdLine; (void)show;

    wchar_t exe[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, exe, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) {
        show_error(L"无法定位程序目录。");
        return 1;
    }
    wchar_t *slash = wcsrchr(exe, L'\\');
    if (slash) *slash = 0;

    wchar_t py[MAX_PATH];
    wchar_t main_py[MAX_PATH];
    _snwprintf_s(py, MAX_PATH, _TRUNCATE, L"%ls\\runtime\\pythonw.exe", exe);
    _snwprintf_s(main_py, MAX_PATH, _TRUNCATE, L"%ls\\main.py", exe);

    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES) {
        show_error(L"没有找到 runtime\\pythonw.exe。\n请确认解压完整，不要只复制 exe。");
        return 1;
    }

    wchar_t cmd[32768];
    _snwprintf_s(cmd, 32768, _TRUNCATE, L"\"%ls\" \"%ls\"", py, main_py);

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, exe, &si, &pi)) {
        show_error(L"启动失败。请检查杀毒软件是否拦截了 runtime\\pythonw.exe。");
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
