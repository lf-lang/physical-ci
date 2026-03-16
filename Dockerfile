FROM ubuntu:latest

RUN apt-get update && apt-get install -y curl default-jdk && rm -rf /var/lib/apt/lists/*
RUN curl -Ls https://install.lf-lang.org | bash -s cli
