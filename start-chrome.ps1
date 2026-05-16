$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = $env:LOCALAPPDATA + "\VKAdminBot\chrome-profile"
if (-not (Test-Path $profile)) { New-Item -ItemType Directory -Path $profile | Out-Null }
$ud = "--user-data-dir=" + $profile
Start-Process $chrome -ArgumentList @("--remote-debugging-port=9222", "--remote-allow-origins=*", $ud, "--no-first-run", "--no-default-browser-check", "https://vk.com")
Write-Host "Chrome zapuschen na portu 9222" -ForegroundColor Green
