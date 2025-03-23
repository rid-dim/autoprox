import asyncio
from autonomi_client import Client

async def main():
    # Connect to network
    client = await Client.init()


    data_address = "a7d2fdbb975efaea25b7ebe3d38be4a0b82c1d71e9b89ac4f37bc9f8677826e0"
    # this is the binary data of the image of a dog
    dog_picture = await client.data_get_public(data_address)

    with open('dog.png', 'wb') as f:
        f.write(dog_picture)

# Run the main function
if __name__ == "__main__":
    asyncio.run(main())

# for a fastapi server the the proxy server address should e.g. be:
# http://localhost:17017/v0/data/get/public/a7d2fdbb975efaea25b7ebe3d38be4a0b82c1d71e9b89ac4f37bc9f8677826e0/dog.png
# that dog.png is no info available on the network, it gets used to make the binary data available "as file" on that address and the name can be chosen freely.