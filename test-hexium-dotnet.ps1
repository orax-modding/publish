# Replicates exactly how tcli (.NET HttpClient + AuthenticationHeaderValue)
# sends the initiate-upload request, to compare with the raw-header result.
$ErrorActionPreference = 'Stop'
$line = Get-Content .env | Where-Object { $_ -match '^HEXIUM_TCLI_AUTH_TOKEN\s*=' } | Select-Object -First 1
$token = ($line -replace '^HEXIUM_TCLI_AUTH_TOKEN\s*=\s*', '').Trim()
if (-not $token) { Write-Host 'Token missing in .env'; exit 1 }

# 1) Check how AuthenticationHeaderValue stores the token (same class tcli uses)
$hdr = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $token)
Write-Host "token length      : $($token.Length)"
Write-Host "header parameter  : length=$($hdr.Parameter.Length) equal=$($hdr.Parameter -eq $token)"
Write-Host "header ToString   : length=$($hdr.ToString().Length)"

# 2) Send the exact tcli-style request (DefaultRequestHeaders.Authorization)
$uri = 'https://hexium.gg/api/experimental/usermedia/initiate-upload/'
$client = [System.Net.Http.HttpClient]::new()
$client.DefaultRequestHeaders.Authorization = $hdr
$json = '{"filename":"publish.zip","file_size_bytes":1024}'
$content = [System.Net.Http.StringContent]::new($json, [System.Text.Encoding]::UTF8, 'application/json')
try {
    $resp = $client.PostAsync($uri, $content).GetAwaiter().GetResult()
    $body = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    Write-Host ".NET HttpClient POST -> $([int]$resp.StatusCode) $body"
}
catch {
    Write-Host ".NET HttpClient POST -> EXC $($_.Exception.Message)"
}
finally {
    $client.Dispose()
}