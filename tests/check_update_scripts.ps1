$source = Get-Content setup.ps1 -Raw
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$null,[ref]$null)
$functionAst = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-Update'},$true)
Invoke-Expression $functionAst.Extent.Text
function Write-Header {param($Text)}
function Write-Info {param($Text)}
function Write-Success {param($Text) $script:reportedSuccess=$true}
foreach($failure in 1..4) {
 $script:count=0;$script:reportedSuccess=$false;$script:failure=$failure
 function docker {$script:count++; $global:LASTEXITCODE=0;if($script:count -eq $script:failure){$global:LASTEXITCODE=17}}
 $caught=$false
 try {Invoke-Update}catch{$caught=$true}
 if(-not $caught -or $script:reportedSuccess -or $script:count -ne $failure){throw "Failure stage $failure not handled"}
}
Write-Output 'PASS: PowerShell update stops at each failed stage and never reports success'

$global:LASTEXITCODE = 0
