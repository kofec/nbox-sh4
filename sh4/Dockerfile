# Toolchain STLinux 2.4 (sh4-linux-gcc 4.8.4-139 - tym samym zbudowano jadro
# GraterliaOS 2.6.32.61_stm24_0217 na nBoxach ADB 5800) do modulow jadra
# i programow. RPM-y z https://github.com/Duckbox-Developers/stlinux (rewizja
# STLINUX_REV), sprawdzane sha256 z rpm.sha256:
#   stlinux24-cross-sh4-{binutils-2.24.51.0.3-77,cpp-4.8.4-139,gcc-4.8.4-139}.i386.rpm
#   stlinux24-sh4-{glibc,glibc-dev}-2.14.1-59.sh4.rpm, stlinux24-sh4-libgcc-4.8.4-149.sh4.rpm,
#   stlinux24-sh4-linux-kernel-headers-2.6.32.46-48.noarch.rpm
# glibc 2.14.1 jest ta sama co w /lib na boxach; rpm-y sh4 laduja w sysroot
# gcc (/opt/STM/STLinux-2.4/devkit/sh4/target).
#
#   docker build -t nbox-sh4:4.8.4 sh4
FROM ubuntu:18.04
RUN dpkg --add-architecture i386 && apt-get update && \
    apt-get install -y --no-install-recommends build-essential bc perl \
        rpm2cpio cpio git patch file ca-certificates libncurses5-dev wget \
        libc6:i386 zlib1g:i386 && \
    rm -rf /var/lib/apt/lists/*
ARG STLINUX_REV=fd1130e8f7a78570c9697d80a866628bad36c93d
COPY rpm.sha256 /tmp/rpm/
RUN cd /tmp/rpm && \
    for r in $(awk '{ print $2 }' rpm.sha256); do \
        wget -q "https://raw.githubusercontent.com/Duckbox-Developers/stlinux/$STLINUX_REV/$r"; \
    done && \
    sha256sum -c rpm.sha256 && \
    cd / && for r in /tmp/rpm/*.rpm; do rpm2cpio $r | cpio -idm --quiet; done && \
    rm -rf /tmp/rpm
ENV PATH=/opt/STM/STLinux-2.4/devkit/sh4/bin:$PATH
WORKDIR /work
