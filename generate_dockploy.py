import re

with open('docker-compose.yml', 'r') as f:
    content = f.read()

# Replace volumes in the odysseus service
replacements = [
    (r'- \$\{APP_DATA_DIR:-./data\}:/app/data:z', '- odysseus-data:/app/data:z'),
    (r'- \$\{APP_LOGS_DIR:-./logs\}:/app/logs:z', '- odysseus-logs:/app/logs:z'),
    (r'- \$\{APP_DATA_DIR:-./data\}/ssh:/app/\.ssh:z', '- odysseus-ssh:/app/.ssh:z'),
    (r'- \$\{APP_DATA_DIR:-./data\}/huggingface:/app/\.cache/huggingface:z', '- odysseus-huggingface:/app/.cache/huggingface:z'),
    (r'- \$\{APP_DATA_DIR:-./data\}/local:/app/\.local:z', '- odysseus-local:/app/.local:z')
]

for old, new in replacements:
    content = re.sub(old, new, content)

# Check if volumes are already at the bottom
volumes_to_add = """
  odysseus-data:
  odysseus-logs:
  odysseus-ssh:
  odysseus-huggingface:
  odysseus-local:
"""

if "odysseus-data:" not in content:
    content += volumes_to_add

with open('dockploy-compose.yml', 'w') as f:
    f.write(content)

print("dockploy-compose.yml generated successfully!")
