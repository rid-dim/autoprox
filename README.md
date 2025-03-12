# Simple HTTP Proxy for Autonomy Network

## IMPORTANT SECURITY NOTICE!!!!!

Using this HTTP proxy will completely undermine your browser's Cross Site Scripting security measures. Only access sites or applications on the Autonomi Network that you trust, and preferably use Immutable Data Addresses instead of pointers or names, especially when dealing with applications that may handle tokens.

While Immutable Data can generally be considered trustworthy if the source is reliable, it is important to note that such data or programs may still interact with pointers to other content that could change at any time.

This tool is provided without any warranties, and you use it at your own risk. The Autonomi Network offers significant capabilities, but with that power comes substantial risks. Exercise extreme caution regarding the sites and applications you choose to visit.


## Overview
This Python package provides a simple HTTP proxy server to access the Autonomi Network. 

Currently the only supported Data Type is chunks/files.

TODO:
- Pointer
- Scratchpad
- GraphEntry
- Register
- Graph (?)

### Goals

The Idea is to create a simple FastAPI server that wraps all basic operations for Datatypes into a simple REST API that can be installed via pip and doesn't require docker/rust to be installed on the system. An easy entry into the Autonomi Network.

### Design

Simple Fastapi server served via Uvicorn that comes with a nice Swagger doc website and an OpenAPI interface description.
In the Server it just wraps the autonomi-client functionality.

To not send a Private Key across the wire repeatedly the proxy does have a route to either import a specified Private Key or set up a wallet on its own and returns an access token as answer. DO NOT LOOSE THAT ACCESS Token!!! the private key/wallet is stored AES encrypted and token on it are lost if you loose that Token (that is used as symmetric key to access the private key for all put operations)

I Repeat (!) when using the PUT-capabilities you need to handle the Token with care! If you loose it (and didn't import a Private Key you still have a backup from) your token are lost!


### Operations

GET:
- getting Data public/private - no payment required

PUT:
- uploading/updating data (pointer, scratchpad, chunks/files)


since the current version only implements immutable data there will just be 1 GET and 1 PUT route for them as well as 1 additional PUT route to import/generate a PrivateKey. 

endpoint of the server:

http://localhost:17017/v0/docs


## Installation and Usage

### Installation

You can install autoprox directly from PyPI:

```bash
pip install autoprox
```

Or with uv:

```bash
uv pip install autoprox
```

### Usage

After installation, you can start the proxy server by running:

```bash
autoprox
```

By default, the server will run on `localhost:17017`. You can customize this with command-line arguments:

```bash
autoprox --host 0.0.0.0 --port 8000
```

The Swagger API documentation will be available at:

```
http://localhost:17017/v0/docs
```

### Example Access

To access a file from the Autonomi Network:

```
http://localhost:17017/v0/data/get/public/{data_address}/{filename}
```

For example:

```
http://localhost:17017/v0/data/get/public/a7d2fdbb975efaea25b7ebe3d38be4a0b82c1d71e9b89ac4f37bc9f8677826e0/dog.png
```

## Links

- [Autonomi](https://autonomi.com)
- [Autonomi Developer Documentation](https://docs.autonomi.com/developers/how-to-guides/build-apps-with-python)
- [autonomi-client on PyPI](https://pypi.org/project/autonomi-client/)
