Param(
    [string]$ApiUrl = "https://agent.legittai.com",
    [string]$RootPath = (Get-Location).Path
)

# 1) Ensure our three main dirs exist
$toBe = Join-Path $RootPath "to_be_processed"
$proc = Join-Path $RootPath "processing"
$done = Join-Path $RootPath "processed"

foreach ($d in @($toBe, $proc, $done)) {
    if (-not (Test-Path $d)) {
        New-Item -Path $d -ItemType Directory | Out-Null
    }
}

# 2) Initialize daily move-log
$dateStr = Get-Date -Format "yyyy-MM-dd"
$moveLogPath = Join-Path $toBe "$dateStr`_move.log"
if (-not (Test-Path $moveLogPath)) {
    New-Item -Path $moveLogPath -ItemType File -Force | Out-Null
}
Write-Host "Using daily move-log: $moveLogPath"

# 3) Process all enquiry folders
$enquiries = Get-ChildItem -Path $toBe -Directory
if (-not $enquiries) {
    Write-Host "No enquiries found in '$toBe'. Exiting."
    exit 0
}

foreach ($enq in $enquiries) {
    $regNo = $enq.Name
    $src = $enq.FullName
    $mid = Join-Path $proc $regNo

    Write-Host ""
    Write-Host "=== Processing enquiry '$regNo' ==="

    # Move to processing
    Move-Item -Path $src -Destination $mid -Force
    Write-Host "Moved '$regNo' to processing"

    # Upload files via curl
    $files = Get-ChildItem -Path $mid -File
    $curlArgs = @()
    foreach ($file in $files) {
        $curlArgs += "-F"
        $curlArgs += "files=@$($file.FullName)"
    }

    $raw = & curl.exe -s -X POST "$ApiUrl/uploadfile/" -F "reg_no=$regNo" @curlArgs
    Write-Host "Upload response received."

    # Log uploaded files
    $dateTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    foreach ($file in $files) {
        Add-Content -Path $moveLogPath -Value "$dateTime - [$regNo] Uploaded: $($file.Name)"
    }
    Write-Host "Appended upload entries to move-log"

    # Parse JSON response
    $obj = $raw | ConvertFrom-Json

    # Save processing_log
    $procLogPath = Join-Path $mid "processing_log.log"
    $obj.processing_log | Out-File -FilePath $procLogPath -Encoding utf8
    Write-Host "Saved processing log to $procLogPath"

    # Wait a bit before downloading Excel
    Start-Sleep -Seconds 2

    # Download Excel without specifying folder param
    $excelUrl = "$ApiUrl/download/excel"
    $excelDest = Join-Path $mid "combined_data.xlsx"

    Write-Host "Downloading Excel from:"
    Write-Host $excelUrl
    Write-Host "Saving to:"
    Write-Host $excelDest

    try {
        Invoke-WebRequest -Uri $excelUrl -OutFile $excelDest -UseBasicParsing -ErrorAction Stop

        $fileContent = Get-Content -Path $excelDest -Raw

        if ($fileContent.Trim().StartsWith('{')) {
            Write-Warning "Server returned JSON instead of Excel. Likely an error:"
            Write-Host $fileContent
        }
        elseif ((Get-Item $excelDest).Length -lt 2048) {
            Write-Warning "Downloaded file is smaller than expected - possibly incomplete or invalid."
        } else {
            Write-Host "Excel downloaded successfully."
        }
    }
    catch {
        Write-Error "Failed to download Excel: $_"
    }

    # Move to processed
    $final = Join-Path $done $regNo
    Move-Item -Path $mid -Destination $final -Force
    Write-Host "Moved '$regNo' to processed"
}

Write-Host ""
Write-Host "All enquiries processed successfully."
