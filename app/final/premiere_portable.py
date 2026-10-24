"""Small, optional Windows relinker for downloaded FCP7 XML projects.

The XML exported on the render host contains that host's absolute media paths.
Premiere can relink those files, but this helper makes the ZIP usable after it is
extracted to any Windows folder without changing the original XML.
"""

README = """HEXA Premiere project
=====================

للاستخدام على ويندوز: فك ضغط ZIP كاملاً، ثم شغّل RELINK_MEDIA.cmd من المجلد.
سيتكوّن ملفان ينتهيان بـ _LOCAL.xml. افتح المطلوب من Premiere عبر File > Import،
واترك مجلد *_media بجانب ملف XML. الملفات الأصلية محفوظة كما هي.

الصور والصوت على مقاطع ومسارات منفصلة. النص والأسهم مقاطع شفافة يمكن تحريكها
واستبدالها، لكن تعديل حروفها أو مسارات رسمها ليس تحريراً أصلياً داخل Premiere.

1. Extract this entire ZIP to a folder on your Windows computer.
2. Double-click RELINK_MEDIA.cmd in that folder.
3. In Premiere Pro, use File > Import and choose the *_LOCAL.xml file for
   YouTube or Reels. Keep each matching *_media folder beside the XML.

The original XML files are retained. If you prefer, import one directly and use
Premiere's Link Media dialog to point to its matching *_media folder.

Artwork is in separate timeline clips with position, scale and opacity controls.
Narration, combined sound effects and music have separate audio tracks. Text and
arrows are separate transparent clips, but their contents are rendered media,
not native Premiere text or paths. Some video-only effects do not transfer.
"""

CMD = """@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RELINK_MEDIA.ps1"
if errorlevel 1 pause
"""

SCRIPT = r'''$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$projects = @(Get-ChildItem -LiteralPath $root -Filter '*_PREMIERE.xml' -File)
if ($projects.Count -eq 0) { throw 'No Premiere XML files found beside this script.' }
foreach ($project in $projects) {
    $media = Join-Path $root ($project.BaseName + '_media')
    if (-not (Test-Path -LiteralPath $media -PathType Container)) {
        throw ('Missing media folder: ' + $media)
    }
    $xml = New-Object System.Xml.XmlDocument
    $xml.Load($project.FullName)
    $refs = @($xml.SelectNodes('//file/pathurl'))
    if ($refs.Count -eq 0) { throw ('No media references in ' + $project.Name) }
    foreach ($ref in $refs) {
        $source = [System.Uri]::new($ref.InnerText)
        if ($source.Scheme -ne 'file') { throw ('Unexpected media URL in ' + $project.Name) }
        $name = [System.IO.Path]::GetFileName([System.Uri]::UnescapeDataString($source.AbsolutePath))
        if ([string]::IsNullOrWhiteSpace($name)) { throw ('Invalid media name in ' + $project.Name) }
        $local = Join-Path $media $name
        if (-not (Test-Path -LiteralPath $local -PathType Leaf)) {
            throw ('Missing media: ' + $local)
        }
        $ref.InnerText = ([System.Uri]::new((Resolve-Path -LiteralPath $local).Path)).AbsoluteUri
    }
    $output = Join-Path $root ($project.BaseName + '_LOCAL.xml')
    $xml.Save($output)
    Write-Host ('Ready: ' + $output)
}
'''


def portable_files() -> dict[str, bytes]:
    return {
        "README_FIRST.txt": README.encode("utf-8"),
        "RELINK_MEDIA.cmd": CMD.encode("ascii"),
        "RELINK_MEDIA.ps1": SCRIPT.encode("utf-8-sig"),
    }
