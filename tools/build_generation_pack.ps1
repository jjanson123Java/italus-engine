$projectRoot = "C:\Users\jajanson\OneDrive - Cisco\Documents\Italus novel\ITALUS_MASTER_FOLDER"
$sourceMergePath = Join-Path $projectRoot "canon_packs\ITALUS_KNOWLEDGE_PACK_GENERATION_SOURCE_MERGE.txt"

# Files approved as source material for the GENERATION pack
$sourceFiles = @(
    "ITALUS_BOOK_GENERATION_ENGINE.txt",
    "ITALUS_SCENE_GENERATOR_MATRIX.txt"
)

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$header = @"
ITALUS KNOWLEDGE PACK — GENERATION SOURCE MERGE
AUTO-BUILT FROM APPROVED GENERATION SOURCES
============================================

"@

[System.IO.File]::WriteAllText($sourceMergePath, $header, $utf8NoBom)

foreach ($file in $sourceFiles) {
    $fullPath = Join-Path $projectRoot $file

    if (Test-Path $fullPath) {
        Write-Host "Appending: $file"

        $divider = @"

============================================================
SOURCE FILE: $file
============================================================

"@

        [System.IO.File]::AppendAllText($sourceMergePath, $divider, $utf8NoBom)

        $content = [System.IO.File]::ReadAllText($fullPath, [System.Text.Encoding]::UTF8)
        [System.IO.File]::AppendAllText($sourceMergePath, $content, $utf8NoBom)
        [System.IO.File]::AppendAllText($sourceMergePath, "`r`n`r`n", $utf8NoBom)
    }
    else {
        Write-Warning "Missing file: $file"
    }
}

Write-Host ""
Write-Host "Generation source merge complete:"
Write-Host $sourceMergePath