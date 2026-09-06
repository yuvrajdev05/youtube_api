$ffmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
$zipPath = "D:\ffmpeg.zip"
$extractPath = "D:\ffmpeg_temp"
$finalPath = "D:\ffmpeg"

Write-Host "Downloading ffmpeg..."
Invoke-WebRequest -Uri $ffmpegUrl -OutFile $zipPath

Write-Host "Extracting..."
Expand-Archive -Path $zipPath -DestinationPath $extractPath

Write-Host "Moving files..."
Move-Item "$extractPath\ffmpeg-master-latest-win64-gpl\*" $finalPath -Force

Write-Host "Cleaning up..."
Remove-Item -Recurse -Force $extractPath
Remove-Item -Force $zipPath

Write-Host "Done!"
