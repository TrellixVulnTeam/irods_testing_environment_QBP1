FROM debian:11

RUN \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    wget \
    apt-transport-https \
    libfuse2 \
    unixodbc \
    rsyslog \
    netcat \
    gnupg \
    lsb-release \
    python3 \
    python3-distro \
    python3-psutil \
    python3-jsonschema \
    python3-requests \
    python3-pip \
    libcurl4-gnutls-dev \
    unixodbc-dev \
    systemd \
  && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/* /tmp/*

RUN pip3 install xmlrunner distro

ENV DEBIAN_FRONTEND=noninteractive

RUN wget -qO - https://packages.irods.org/irods-signing-key.asc | apt-key add - && \
    echo "deb [arch=amd64] https://packages.irods.org/apt/ bullseye main" | tee /etc/apt/sources.list.d/renci-irods.list

RUN wget -qO - https://core-dev.irods.org/irods-core-dev-signing-key.asc | apt-key add - && \
    echo "deb [arch=amd64] https://core-dev.irods.org/apt/ bullseye main" | tee /etc/apt/sources.list.d/renci-irods-core-dev.list

RUN mkdir -p /irods_testing_environment_mount_dir && chmod 777 /irods_testing_environment_mount_dir

ENTRYPOINT ["bash", "-c", "until false; do sleep 2147483647d; done"]
