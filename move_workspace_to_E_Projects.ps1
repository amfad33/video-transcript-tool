$ErrorActionPreference = "Stop"

$source = "C:\Users\Amir Hosein\Documents\New project"
$projectsRoot = "E:\Projects"
$destination = Join-Path $projectsRoot "New project"

if (-not (Test-Path -LiteralPath $source)) {
    throw "Source folder does not exist: $source"
}

if (-not (Test-Path -LiteralPath $projectsRoot)) {
    New-Item -ItemType Directory -Path $projectsRoot | Out-Null
}

if (Test-Path -LiteralPath $destination) {
    throw "Destination already exists: $destination"
}

Set-Location -LiteralPath "$env:SystemDrive\"
Move-Item -LiteralPath $source -Destination $projectsRoot
Write-Host "Moved workspace to: $destination"
