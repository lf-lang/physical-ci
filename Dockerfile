FROM ghcr.io/actions/actions-runner:latest

USER root
RUN apt-get update && apt-get install -y curl default-jdk cmake build-essential python3-dev python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install --break-system-packages numpy evdev "trossen_arm==1.10.*"
RUN curl -Ls https://install.lf-lang.org | bash -s cli
ENV PATH="/root/.local/bin:${PATH}"
ENV RUNNER_ALLOW_RUNASROOT=1
