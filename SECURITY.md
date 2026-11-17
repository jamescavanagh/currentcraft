# Security and disclosure

Do not publish enterprise data or credentials in issues, pull requests or example files. Use an organization's approved private reporting channel; this candidate deliberately invents no maintainer contact address.

Before release, review source rights, Git index/history, generated archives and dependency advisories. .gitignore does not remove tracked files or previous commits. Treat suspected credential disclosure as an incident and rotate affected credentials. Reference/embedding/model artifacts may reveal enterprise content without visible personal identifiers.

The local scanner and allowlist exporter reduce accidental inclusion; they do not prove absence of secrets, vulnerabilities or confidential algorithms. No remote vulnerability audit or hosted CI run is claimed.
