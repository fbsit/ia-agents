$ErrorActionPreference = "Stop"

$jdk21Path = "C:\Users\Felipe\scoop\apps\temurin21-jdk\current"
if (-not (Test-Path $jdk21Path)) {
  throw "No se encontro JDK 21 en $jdk21Path"
}

$env:JAVA_HOME = $jdk21Path
$env:Path = "$env:JAVA_HOME\bin;$env:Path"

$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
      return
    }
    $parts = $line -split "=", 2
    if ($parts.Length -ne 2) {
      return
    }
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    Set-Item -Path "Env:$name" -Value $value
  }
}

Write-Host "JAVA_HOME=$env:JAVA_HOME"
java -version

& "$PSScriptRoot\mvnw.cmd" spring-boot:run
