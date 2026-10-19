@echo off
rem SAEngine command line (python -m saengine.cli, docs\cli.md) with the Python bundled in the
rem installation. build-installer.ps1 puts this file in <install folder>\bin\saengine.cmd; the
rem setup's task "Add the saengine command to PATH" adds that folder to the user's PATH.
rem The Code - OSS launcher that opens a folder or file in the SAEngine window is bin\saengine-app.cmd.
rem The app itself calls bin\<applicationName>.cmd with --file-write / --file-chmod for "Retry as
rem Admin" saves (nativeHostMainService.writeElevated, run elevated through sudo-prompt). Those
rem internal Code - OSS switches go to the window launcher, which handles them.
setlocal
if /i "%~1"=="--file-write" goto app
if /i "%~1"=="--file-chmod" goto app
set "SAENGINE_PYTHON=%~dp0..\resources\python\python.exe"
if not exist "%SAENGINE_PYTHON%" (
	echo saengine: the bundled Python is missing: "%SAENGINE_PYTHON%". Repair or reinstall SAEngine. 1>&2
	exit /b 9009
)
"%SAENGINE_PYTHON%" -I -m saengine.cli %*
exit /b %ERRORLEVEL%
:app
call "%~dp0saengine-app.cmd" %*
exit /b %ERRORLEVEL%
