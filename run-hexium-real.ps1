$null = [System.Management.Automation.Language.Parser]::ParseFile("$PSScriptRoot/test-act.ps1", [ref]$null, [ref]$null)
Write-Host "Syntax OK"

$zip = Join-Path $PSScriptRoot "dist/publish.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }

& "$PSScriptRoot/test-act.ps1" -Platform hexium -Tag v0.0.0 > "$PSScriptRoot/hexium-test-real.log" 2>&1

Write-Host "Test termine. Consultez hexium-test-real.log"