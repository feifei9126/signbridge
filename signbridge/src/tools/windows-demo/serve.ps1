# SignBridge Demo — Windows launcher
# Serves the bundled site on 127.0.0.1 and opens it in Chrome.
# Uses only components that ship with Windows; no install, no admin rights.

$ErrorActionPreference = 'Stop'
$root = Join-Path $PSScriptRoot 'site'
$rootFull = [System.IO.Path]::GetFullPath($root)

Add-Type -AssemblyName System.Net.HttpListener

$types = @{
  '.html' = 'text/html; charset=utf-8'
  '.js'   = 'text/javascript; charset=utf-8'
  '.mjs'  = 'text/javascript; charset=utf-8'
  '.css'  = 'text/css; charset=utf-8'
  '.json' = 'application/json; charset=utf-8'
  '.png'  = 'image/png'
  '.jpg'  = 'image/jpeg'
  '.jpeg' = 'image/jpeg'
  '.svg'  = 'image/svg+xml'
  '.glb'  = 'model/gltf-binary'
  '.wasm' = 'application/wasm'
  '.ico'  = 'image/x-icon'
}

# Pick a free port in a narrow range so a stale instance cannot silently win.
$listener = $null
$port = 0
foreach ($candidate in 8731..8760) {
  try {
    $l = New-Object System.Net.HttpListener
    $l.Prefixes.Add("http://127.0.0.1:$candidate/")
    $l.Start()
    $listener = $l
    $port = $candidate
    break
  } catch {
    if ($l -and $l.IsListening) { $l.Stop() }
  }
}
if (-not $listener) {
  Write-Host 'SignBridge Demo could not start: no free local port.' -ForegroundColor Red
  Read-Host 'Press Enter to close'
  exit 1
}

Write-Host ''
Write-Host '  SignBridge Demo 2.1.1' -ForegroundColor Cyan
Write-Host "  Serving http://127.0.0.1:$port/" -ForegroundColor DarkGray
Write-Host '  Keep this window open while using the demo.' -ForegroundColor DarkGray
Write-Host '  Close this window to stop.' -ForegroundColor DarkGray
Write-Host ''

$url = "http://127.0.0.1:$port/demo/index.html"
$chrome = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($chrome) {
  Start-Process -FilePath $chrome -ArgumentList @("--new-window", $url)
} else {
  Write-Host '  Chrome was not found. Opening in your default browser instead.' -ForegroundColor Yellow
  Start-Process $url
}

# Single-threaded accept loop; the demo only ever has one client on localhost.
while ($listener.IsListening) {
  try {
    $context = $listener.GetContext()
  } catch {
    break
  }
  $request = $context.Request
  $response = $context.Response
  try {
    if ($request.HttpMethod -ne 'GET' -and $request.HttpMethod -ne 'HEAD') {
      $response.StatusCode = 405
      continue
    }
    # Reject anything that is not addressed to our own loopback origin.
    $hostName = $request.Headers['Host']
    if ($hostName -and $hostName -ne "127.0.0.1:$port" -and $hostName -ne "localhost:$port") {
      $response.StatusCode = 403
      continue
    }
    $path = [System.Uri]::UnescapeDataString($request.Url.AbsolutePath)
    if ($path -eq '/' -or $path -eq '') { $path = '/demo/index.html' }
    if ($path.Contains('\') -or $path.Contains([char]0)) {
      $response.StatusCode = 400
      continue
    }
    $relative = $path.TrimStart('/')
    $segments = $relative -split '/'
    if ($segments | Where-Object { $_ -eq '' -or $_ -eq '.' -or $_ -eq '..' }) {
      $response.StatusCode = 400
      continue
    }
    $file = [System.IO.Path]::GetFullPath((Join-Path $rootFull ($segments -join [System.IO.Path]::DirectorySeparatorChar)))
    if (-not $file.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar)) {
      $response.StatusCode = 403
      continue
    }
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
      $response.StatusCode = 404
      continue
    }
    $ext = [System.IO.Path]::GetExtension($file).ToLowerInvariant()
    $response.ContentType = if ($types.ContainsKey($ext)) { $types[$ext] } else { 'application/octet-stream' }
    $response.Headers.Add('Cache-Control', 'no-store')
    $response.Headers.Add('X-Content-Type-Options', 'nosniff')
    $bytes = [System.IO.File]::ReadAllBytes($file)
    $response.ContentLength64 = $bytes.Length
    if ($request.HttpMethod -eq 'GET') {
      $response.OutputStream.Write($bytes, 0, $bytes.Length)
    }
  } catch {
    try { $response.StatusCode = 500 } catch {}
  } finally {
    try { $response.OutputStream.Close() } catch {}
    try { $response.Close() } catch {}
  }
}

$listener.Stop()
$listener.Close()
