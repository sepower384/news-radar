# 돌고 있는 뉴스 레이더 감시 루프만 골라 종료
$stopped = 0
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | ForEach-Object {
    if ($_.CommandLine -and $_.CommandLine -match 'news-radar.*watch\.py') {
        Stop-Process -Id $_.ProcessId -Force
        $stopped++
    }
}
Write-Host "중지한 프로세스: $stopped"
