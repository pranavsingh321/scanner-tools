FROM rust:alpine AS build
RUN apk add --no-cache build-base musl-dev git go
RUN cargo install tokei --locked
RUN go install github.com/boyter/scc/v3@latest

FROM alpine:3.21
RUN apk add --no-cache git ca-certificates nodejs npm python3 py3-pip
COPY --from=build /usr/local/cargo/bin/tokei /usr/local/bin/tokei
COPY --from=build /root/go/bin/scc /usr/local/bin/scc
RUN npm install -g repomix
RUN pip3 install --no-cache-dir --break-system-packages gitingest files-to-prompt
WORKDIR /repo
