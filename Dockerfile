# Multi-stage: build the Go-based recon/scan tools with the official,
# well-maintained golang image (avoids relying on whatever (possibly stale)
# Go toolchain a Kali apt mirror happens to have — ProjectDiscovery tools in
# particular track fairly recent Go language features).
FROM golang:1-bookworm AS gotools

RUN go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest \
 && go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest \
 && go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest \
 && go install -v github.com/projectdiscovery/katana/cmd/katana@latest \
 && go install -v github.com/lc/gau/v2/cmd/gau@latest \
 && go install -v github.com/hahwul/dalfox/v2@latest

# Final image: same distro family as the host this was developed on (Kali),
# so ffuf/sqlmap/nmap package names/behavior match what was actually tested.
FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    ffuf sqlmap nmap \
    ca-certificates curl git gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=gotools /go/bin/ /usr/local/bin/

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

COPY . .

# core/config.py resolves MEGATRON_HOME from its own file location and
# resolves every tool path via shutil.which() with an env-var override
# fallback — no code changes needed to run from /app instead of
# /home/kali/megatron.
CMD ["python3", "megatron", "run"]
