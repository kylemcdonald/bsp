# Teensy

## Remotely uploading to Teensy

Remotely, on the Raspberry Pi, download and compile `teensy_loader_cli`:

```
cd ~ && git clone https://github.com/PaulStoffregen/teensy_loader_cli.git
cd teensy_loader_cli && make
```

Then locally, with Teensyduino, export the compiled binary (command-option-s).

Then run `bash upload-hex.sh` and this will copy the .hex file to the Raspberry Pi and use `teensy_loader_cli` to upload it to the Teensy.