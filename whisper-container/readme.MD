# Whisper container

The following creates a container that takes an audio file from S3, runs whisper model to transcribe it, and returns the transcription to S3.

It's intended to be used in AWS Batch service.

## Pushing it to docker hub

For this image to run it needs to be pushed to docker hub. For that you need to login first using:

```bash
docker login
```

Then you can push the image using:

```bash
docker push manuelsh/platic-whisper:latest
```

## File types accepted

The container takes `.flac` files from S3 with 16000 Hz sample rate.

## Variables

The docker uses the following environment or config variables:

In the `config.py` file:

- `WHISPER_MODEL`: whisper model type, set to large.
- `S3_CREDENTIALS_PATH`: http path to S3 credentials from ec2 AIM role.
- `S3_BUCKET`: S3 bucket where input and output files are stored.

Also, one must run the container with the following environment variables:

- `FILE_NAME`: name of the file to transcribe. The output file will have the same name with a `_result.json` suffix.
- `LANGUAGE`: the language of the audio file. To autodetect the language, set to `auto`.
- `TASK`: the task to run. Set to `transcribe` to transcribe the audio file or `translate` to translate the transcription to English.

## Running the container

The following command builds the container locally, as an example:

```bash
docker build -t whisper .
```

and as an example to run it:

```bash
docker run \
 -e FILE_NAME=b3l01m3ahMQ9pR7DP9DSU5Ukba33_1960547e-d418-40c1-961b-805037a1645e.flac \
 -e LANGUAGE=es \
 -e TASK=transcribe \
 --entrypoint python3 -u main.py\
 -it whisper
```
