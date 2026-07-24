param(
    [string]$Blender = "E:\Blender\blender.exe",
    [ValidateSet("1024", "2048", "4096", "8192")]
    [string]$Size = "1024",
    [switch]$RenderProofs,
    [int]$ProofResolution = 1024
)

$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$Fixture = Join-Path $Repo "reference_assets\folsomsavage_original.blend"
$BuildRoot = [System.IO.Path]::GetFullPath((Join-Path $Repo "build"))
$Output = [System.IO.Path]::GetFullPath((Join-Path $BuildRoot "reference_test_$Size"))
if (-not $Output.StartsWith($BuildRoot + [System.IO.Path]::DirectorySeparatorChar)) {
    throw "Refusing to clean an output path outside the repository build folder."
}
if (Test-Path -LiteralPath $Output) {
    Remove-Item -LiteralPath $Output -Recurse -Force
}
$SourceHashBefore = (Get-FileHash -LiteralPath $Fixture -Algorithm SHA256).Hash
$Arguments = @(
    $Fixture,
    "--background",
    "--python", (Join-Path $Repo "scripts\run_reference_test.py"),
    "--",
    "--repo-root", $Repo,
    "--output-dir", $Output,
    "--size", $Size,
    "--proof-resolution", $ProofResolution
)
if ($RenderProofs) {
    $Arguments += "--render-proofs"
}

& $Blender @Arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
$SourceHashAfter = (Get-FileHash -LiteralPath $Fixture -Algorithm SHA256).Hash
if ($SourceHashBefore -ne $SourceHashAfter) {
    Write-Error "The source Blender fixture changed during processing."
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $Output "folsomsavage_sbf.blend"))) {
    Write-Error "Reference test did not produce the expected Blender output."
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $Output "reference_test_result.json"))) {
    Write-Error "Reference test did not write a PASS result."
    exit 1
}

& $Blender (Join-Path $Output "folsomsavage_sbf.blend") `
    --background `
    --python (Join-Path $Repo "scripts\inspect_output.py") `
    -- `
    --expected-size $Size
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& $Blender --background `
    --python (Join-Path $Repo "scripts\inspect_output.py") `
    -- `
    --glb (Join-Path $Output "folsomsavage_sbf.glb") `
    --expected-size $Size
exit $LASTEXITCODE
