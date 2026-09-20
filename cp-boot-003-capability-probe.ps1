$ErrorActionPreference = 'Stop'
$probePath = Join-Path $PSScriptRoot '.cp-boot-003-temporary.txt'
if (Test-Path -LiteralPath $probePath) { throw 'Probe path already exists' }
try {
    [System.IO.File]::WriteAllText($probePath, 'CP-BOOT-003:first')
    if ([System.IO.File]::ReadAllText($probePath) -cne 'CP-BOOT-003:first') { throw 'Write/read assertion failed' }
    [System.IO.File]::WriteAllText($probePath, 'CP-BOOT-003:second')
    if ([System.IO.File]::ReadAllText($probePath) -cne 'CP-BOOT-003:second') { throw 'Modify/read assertion failed' }
} finally {
    if (Test-Path -LiteralPath $probePath) { Remove-Item -LiteralPath $probePath }
}
if (Test-Path -LiteralPath $probePath) { throw 'Cleanup assertion failed' }
'PASS: create, read, modify, reread, delete; 3 assertions'