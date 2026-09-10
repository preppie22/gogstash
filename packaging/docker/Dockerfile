FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y \
    && apt-get install -y software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y python3.12 python3.12-venv python3.12-dev 
    
RUN apt-get install -y \
        libgl1 \
        libegl1 \
        libwayland-egl1 \
        libxkbcommon0 \
        libxkbcommon-x11-0 \
        libdbus-1-3 \
        libxcb-cursor0 \
        libwayland-cursor0 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-randr0 \
        libxcb-render-util0 \
        libxcb-shape0 \
        libxcb-xinerama0 \
        libxcb-xfixes0 \
        libx11-xcb1 \
        libfontconfig1 \
        libfreetype6 \
        libwayland-client0 \
        binutils \
        curl

RUN curl -L -o /usr/local/bin/appimagetool https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage \
    && chmod +x /usr/local/bin/appimagetool
WORKDIR /build
COPY . /build/

RUN python3.12 -m venv /build/.venv
RUN /build/.venv/bin/pip install ".[dev,packaging]"
RUN /build/.venv/bin/pyinstaller --add-data "/build/src/gogstash/icons:gogstash/icons" --onedir --windowed --name gogstash /build/.venv/bin/gogstash
RUN mkdir -p /build/AppDir/usr/bin \
    && cp -r /build/dist/gogstash /build/AppDir/usr/bin/ \
    && cp -r /build/packaging/appimage/* /build/AppDir/ \
    && chmod +x /build/AppDir/AppRun
RUN appimagetool --appimage-extract-and-run /build/AppDir /build/gogstash-x86_64.AppImage \
    && chmod +x /build/gogstash-x86_64.AppImage