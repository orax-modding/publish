$env:HEXIUM_API_TOKEN = 'fake_token'
$zip = Join-Path $PSScriptRoot 'dist/publish.zip'
if (Test-Path $zip) { Remove-Item $zip -Force }
& "$PSScriptRoot/test-act.ps1" -Platform hexium -Tag v0.0.0 > "$PSScriptRoot/hexium-test-output.log" 2>&1