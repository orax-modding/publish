<#
.SYNOPSIS
    Local test script for the GitHub Actions workflows (Nexus Mods / Thunderstore).

.DESCRIPTION
    This script makes it easier to run `act` to test the workflows
    defined in .github/workflows/ without having to type the long
    commands manually.

    It creates or updates the required JSON event file and runs
    `act release` with the proper secrets and variables.

    Nexus Mods configuration used by the workflow:
      - NEXUS_MODS_MOD_ID  (variable) mod ID on Nexus Mods
      - NEXUS_MODS_FILE_ID (variable) file ID to upload the new version to
      - NEXUS_API_KEY      (secret)   Nexus Mods API key

    Each value is read from the environment variable of the same name
    when it is already set; otherwise the script prompts for it.

.PARAMETER Tag
    The version/tag to test (defaults to "v0.1.0").

.PARAMETER DryRun
    Passes -n/--dryrun to act so the workflow is validated without
    being executed in a container.

.PARAMETER Image
    Docker image used to run the "ubuntu-latest" job locally. Defaults to
    ghcr.io/catthehacker/ubuntu:gh-latest because it ships the gh CLI,
    which the workflow needs for "gh release download" (the default act
    image does not include gh).

.EXAMPLE
    .\test-act.ps1 -Tag v0.1.0
    Runs the publication workflow with the tag v0.1.0.

.EXAMPLE
    .\test-act.ps1 -DryRun
    Validates the workflow without executing it.
#>

param(
    [Parameter(Mandatory = $false)]
    [string]$Tag = "v0.1.0",

    [Parameter(Mandatory = $false)]
    [switch]$DryRun,

    [Parameter(Mandatory = $false)]
    [string]$Image = "ghcr.io/catthehacker/ubuntu:gh-latest"
)

# Repository path (script directory, current directory as fallback)
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not (Test-Path $RepoRoot)) {
    $RepoRoot = (Get-Location).Path
}
Set-Location $RepoRoot

# JSON event file for act (payload of the "release" event that triggers the workflow)
$EventsDir = Join-Path $RepoRoot "events"
if (-not (Test-Path $EventsDir)) {
    New-Item -ItemType Directory -Path $EventsDir | Out-Null
}
$EventFile = Join-Path $EventsDir "release.json"

# Repository name: "owner/repo" -> "repo" (folder name as fallback when
# GITHUB_REPOSITORY is not defined on the local machine)
$RepositoryFullName = $env:GITHUB_REPOSITORY
if (-not $RepositoryFullName) {
    $RepositoryFullName = Split-Path -Leaf $RepoRoot
}
$RepositoryName = $RepositoryFullName -replace '.*[\\/]', ''

# Recreate the event file when it is missing, outdated or built for another tag
$ExistingEvent = $null
if (Test-Path $EventFile) {
    try {
        $ExistingEvent = Get-Content -Path $EventFile -Raw | ConvertFrom-Json
    }
    catch {
        $ExistingEvent = $null
    }
}
$NeedsRefresh = $true
if ($ExistingEvent -and $ExistingEvent.release -and ($ExistingEvent.action -eq "published")) {
    $NeedsRefresh = ([string]$ExistingEvent.release.tag_name -ne $Tag)
}
if ($NeedsRefresh) {
    # Basic template: adjust the fields if your workflow expects other keys
    $Json = @{
        action     = "published"
        repository = @{
            name      = $RepositoryName
            full_name = $RepositoryFullName
        }
        release    = @{
            tag_name = $Tag
            name     = "Version $Tag"
        }
    }
    # Write UTF-8 without BOM: act cannot parse an event file starting with a BOM
    $JsonText = $Json | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText($EventFile, $JsonText, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Event file created: $EventFile"
}
else {
    Write-Host "Existing event file: $EventFile"
}

# Secrets and variables to pass to act (environment variables are reused
# when they are already set, the prompt is only used as a fallback)
$NexusModId = $env:NEXUS_MODS_MOD_ID
if (-not $NexusModId) {
    $NexusModId = Read-Host "Enter NEXUS_MODS_MOD_ID (or leave empty)"
}
$NexusFileId = $env:NEXUS_MODS_FILE_ID
if (-not $NexusFileId) {
    $NexusFileId = Read-Host "Enter NEXUS_MODS_FILE_ID (or leave empty)"
}
$NexusApiKey = $env:NEXUS_API_KEY
if (-not $NexusApiKey) {
    $NexusApiKey = Read-Host "Enter NEXUS_API_KEY (or leave empty)"
}

# Build the act command arguments
# (act flags: -C working directory, -W workflow file, -e event file, -j job,
#  -n dry run, -P platform image, --var repository variable, -s secret)
$WorkflowFile = Join-Path $RepoRoot ".github\workflows\upload-nexusmods.yml"
$ActArgs = @(
    "release"
    "-C", $RepoRoot
    "-W", $WorkflowFile
    "-e", $EventFile
    "-j", "upload"
)
# Map the "ubuntu-latest" runner to an image that ships the gh CLI, which the
# workflow needs for "gh release download" (the default act image lacks gh)
if ($Image) {
    $ActArgs += @("-P", "ubuntu-latest=$Image")
}
if ($DryRun) {
    $ActArgs += "-n"
}
if ($NexusModId) {
    $ActArgs += @("--var", "NEXUS_MODS_MOD_ID=$NexusModId")
}
if ($NexusFileId) {
    $ActArgs += @("--var", "NEXUS_MODS_FILE_ID=$NexusFileId")
}
if ($NexusApiKey) {
    $ActArgs += @("--secret", "NEXUS_API_KEY=$NexusApiKey")
}
# Forward GITHUB_TOKEN when available (needed by "gh release download")
if ($env:GITHUB_TOKEN) {
    $ActArgs += @("--secret", "GITHUB_TOKEN=$env:GITHUB_TOKEN")
}

# Display the command with the secret values masked
$DisplayArgs = $ActArgs | ForEach-Object {
    if ($_ -like "NEXUS_API_KEY=*") { "NEXUS_API_KEY=***" }
    elseif ($_ -like "GITHUB_TOKEN=*") { "GITHUB_TOKEN=***" }
    else { $_ }
}
Write-Host "--- Running the act command ---"
Write-Host ("act " + ($DisplayArgs -join ' '))
Write-Host "---"

& act @ActArgs

Write-Host "`nTest finished. Check the output above for the results."
exit $LASTEXITCODE