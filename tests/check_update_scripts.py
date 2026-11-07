"""Behavior tests for the Bash update function. Run with python3 in an image with Bash."""
from pathlib import Path
import re
import subprocess
import tempfile
script=(Path(__file__).resolve().parents[1]/'setup.sh').read_text()
function=re.search(r'^update_stack\(\) \{.*?^\}',script,re.M|re.S).group()
with tempfile.TemporaryDirectory() as folder:
 log=Path(folder)/'calls'
 for failure in range(1,5):
  log.write_text('')
  wrapper=f"""set -e
write_header() {{ :; }}
docker() {{ count=$((count+1)); echo "$count" >> '{log}'; if [ "$count" = '{failure}' ]; then return 17; fi; }}
count=0
{function}
update_stack
"""
  result=subprocess.run(['bash','-c',wrapper],capture_output=True,text=True)
  assert result.returncode==17
  assert len(log.read_text().splitlines())==failure
  assert 'completed successfully' not in result.stdout
 print('PASS: Bash update stops at all four failed stages without reporting success')
