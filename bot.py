@router.channel_post()
async def get_channel_id(message: Message):
    print("НАЗВАНИЕ КАНАЛА:", message.chat.title)
    print("ID КАНАЛА:", message.chat.id)
    print("ТЕКСТ:", message.text)