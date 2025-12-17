import discord, asyncio,yt_dlp,time, concurrent.futures
from discord.ext import commands;from collections import deque;from functools import partial

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix='b!', intents=intents, help_command=None)
executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
queues = {}
loop_mode = {}
volume_levels = {}
current_songs = {}
voice_clients = {}
alone_timers = {}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -b:a 320k'
}

def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = deque()
    return queues[guild_id]

def get_loop_mode(guild_id):
    if guild_id not in loop_mode:
        loop_mode[guild_id] = 0
    return loop_mode[guild_id]

def set_loop_mode(guild_id, mode):
    loop_mode[guild_id] = mode

def get_volume(guild_id):
    if guild_id not in volume_levels:
        volume_levels[guild_id] = 1.0
    return volume_levels[guild_id]

def set_volume(guild_id, vol):
    volume_levels[guild_id] = vol

def get_current_song(guild_id):
    return current_songs.get(guild_id)

def set_current_song(guild_id, song):
    current_songs[guild_id] = song

async def check_alone_in_channel(guild_id):
    if guild_id in alone_timers:
        alone_timers[guild_id].cancel()
    
    voice_client = voice_clients.get(guild_id)
    if not voice_client or not voice_client.is_connected():
        return
    
    channel = voice_client.channel
    members = [m for m in channel.members if not m.bot]
    
    if len(members) == 0:
        timer = asyncio.create_task(alone_timer(guild_id, channel))
        alone_timers[guild_id] = timer

async def alone_timer(guild_id, channel):
    try:
        await asyncio.sleep(300)
        
        voice_client = voice_clients.get(guild_id)
        if voice_client and voice_client.is_connected():
            members = [m for m in voice_client.channel.members if not m.bot]
            if len(members) == 0:
                try:
                    await voice_client.channel.edit(status=None)
                except:
                    pass
                
                if voice_client.is_playing():
                    voice_client.stop()
                await voice_client.disconnect()
                del voice_clients[guild_id]
                
                if guild_id in queues:
                    queues[guild_id].clear()
                if guild_id in current_songs:
                    del current_songs[guild_id]
                if guild_id in alone_timers:
                    del alone_timers[guild_id]
                
                embed = discord.Embed(
                    description="⏹️ Đã rời khỏi kênh do không có ai trong 5 phút",
                    color=0x2F3136
                )
                
                text_channel = None
                for ch in channel.guild.text_channels:
                    if ch.permissions_for(channel.guild.me).send_messages:
                        text_channel = ch
                        break
                
                if text_channel:
                    await text_channel.send(embed=embed)
    except asyncio.CancelledError:
        pass

async def search_youtube(query):
    def _sync_extract(query_str):
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'source_address': '0.0.0.0',
            'socket_timeout': 10,
            'retries': 3,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if 'http' in query_str:
                info = ydl.extract_info(query_str, download=False)
            else:
                info = ydl.extract_info(f"ytsearch1:{query_str}", download=False)
                if 'entries' in info and len(info['entries']) > 0:
                    info = info['entries'][0]
                else:
                    return None
            
            if not info:
                return None
                
            return {
                'url': info['url'],
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'webpage_url': info.get('webpage_url', ''),
                'uploader': info.get('uploader', 'Unknown')
            }
    
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(executor, _sync_extract, query),
            timeout=20.0
        )
        return result
    except asyncio.TimeoutError:
        print(f"Timeout khi tìm kiếm: {query}")
        return None
    except Exception as e:
        print(f"Lỗi tìm kiếm: {e}")
        return None

async def get_playlist_videos(url):
    def _sync_get_playlist(url_str):
        ydl_opts = {
            'format': 'bestaudio*',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'ignoreerrors': True,
            'nocheckcertificate': True,
            'source_address': '0.0.0.0',
            'socket_timeout': 10,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url_str, download=False)
                if 'entries' in info:
                    videos = []
                    for entry in info['entries']:
                        if entry:
                            videos.append({
                                'title': entry.get('title', 'Unknown'),
                                'url': entry.get('url', ''),
                                'id': entry.get('id', ''),
                                'duration': entry.get('duration', 0),
                                'webpage_url': f"https://youtube.com/watch?v={entry.get('id', '')}"
                            })
                    return videos
                return []
            except:
                return []
    
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(executor, _sync_get_playlist, url),
            timeout=30.0
        )
        return result
    except:
        return []

def format_duration(seconds):
    if not seconds:
        return "🔴 Live"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

async def play_next(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    loop = get_loop_mode(guild_id)
    current = get_current_song(guild_id)
    
    if loop == 1 and current:
        song_info = await search_youtube(current['webpage_url'])
        if song_info:
            await play_song(ctx, song_info)
            return
    
    if loop == 2 and current:
        queue.append(current)
    
    if len(queue) > 0:
        song_info = queue.popleft()
        full_info = await search_youtube(song_info['webpage_url'] if 'webpage_url' in song_info else song_info['url'])
        if full_info:
            await play_song(ctx, full_info)
    else:
        set_current_song(guild_id, None)
        voice_client = voice_clients.get(guild_id)
        if voice_client and voice_client.is_connected():
            try:
                await voice_client.channel.edit(status=None)
            except:
                pass
        embed = discord.Embed(
            description="⏹️ Queue đã kết thúc. Sử dụng `b!play` để phát nhạc mới!",
            color=0x2F3136
        )
        await ctx.send(embed=embed)

async def play_song(ctx, song_info):
    guild_id = ctx.guild.id
    voice_client = voice_clients.get(guild_id)
    
    if not voice_client or not voice_client.is_connected():
        return
    
    set_current_song(guild_id, song_info)
    
    try:
        await voice_client.channel.edit(status=f"Đang nghe: {song_info['title'][:480]}")
    except:
        pass
    
    def after_playing(error):
        if error:
            print(f"Error: {error}")
        asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
    
    try:
        source = discord.FFmpegPCMAudio(song_info['url'], **ffmpeg_options)
        volume = get_volume(guild_id)
        audio_source = discord.PCMVolumeTransformer(source, volume=volume)
        voice_client.play(audio_source, after=after_playing)
        
        embed = discord.Embed(
            title="",
            description=f"### 🎵 Đang phát\n**[{song_info['title']}]({song_info['webpage_url']})**",
            color=0x5865F2
        )
        embed.add_field(name="⏱️ Thời lượng", value=f"`{format_duration(song_info['duration'])}`", inline=True)
        embed.add_field(name="📺 Kênh", value=f"`{song_info.get('uploader', 'Unknown')}`", inline=True)
        embed.add_field(name="🔊 Âm lượng", value=f"`{int(volume * 100)}%`", inline=True)
        
        queue_length = len(get_queue(guild_id))
        if queue_length > 0:
            embed.add_field(name="📋 Tiếp theo", value=f"`{queue_length} bài hát`", inline=True)
        
        loop = get_loop_mode(guild_id)
        if loop == 1:
            embed.add_field(name="🔁 Loop", value="`Bài hát`", inline=True)
        elif loop == 2:
            embed.add_field(name="🔁 Loop", value="`Queue`", inline=True)
        
        if song_info['thumbnail']:
            embed.set_thumbnail(url=song_info['thumbnail'])
        
        embed.set_footer(text=f"Yêu cầu bởi {ctx.author.display_name} • By BensGaming", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        embed.timestamp = discord.utils.utcnow()
        
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="❌ Lỗi phát nhạc",
            description=f"```{str(e)}```",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        await play_next(ctx)

@bot.event
async def on_ready():
    print(f'{bot.user} đã sẵn sàng!')
    
    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name="BensMusic | b!help"
    )
    await bot.change_presence(activity=activity)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    if before.channel is not None:
        guild_id = before.channel.guild.id
        if guild_id in voice_clients:
            voice_client = voice_clients[guild_id]
            if voice_client.channel == before.channel:
                await check_alone_in_channel(guild_id)
    
    if after.channel is not None:
        guild_id = after.channel.guild.id
        if guild_id in voice_clients and guild_id in alone_timers:
            voice_client = voice_clients[guild_id]
            if voice_client.channel == after.channel:
                alone_timers[guild_id].cancel()
                del alone_timers[guild_id]

@bot.command(name='play', aliases=['p'])
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        embed = discord.Embed(
            description="❌ Bạn phải ở trong voice channel!",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    channel = ctx.author.voice.channel
    guild_id = ctx.guild.id
    
    if guild_id not in voice_clients or not voice_clients[guild_id].is_connected():
        voice_client = await channel.connect()
        voice_clients[guild_id] = voice_client
        await check_alone_in_channel(guild_id)
    
    embed = discord.Embed(
        description=f"🔍 Đang tìm kiếm **{query}**...",
        color=0x5865F2
    )
    status_msg = await ctx.send(embed=embed)
    
    if 'playlist' in query.lower() or 'list=' in query:
        try:
            videos = await get_playlist_videos(query)
            if videos:
                queue = get_queue(guild_id)
                for video in videos:
                    queue.append(video)
                
                await status_msg.delete()
                embed = discord.Embed(
                    title="",
                    description=f"### 📋 Đã thêm playlist\n**{len(videos)}** bài hát đã được thêm vào hàng đợi",
                    color=0x57F287
                )
                embed.set_footer(text=f"Yêu cầu bởi {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
                await ctx.send(embed=embed)
                
                if not voice_clients[guild_id].is_playing():
                    await play_next(ctx)
            else:
                await status_msg.delete()
                embed = discord.Embed(
                    description="❌ Không thể tải playlist hoặc quá thời gian chờ",
                    color=0xED4245
                )
                await ctx.send(embed=embed)
        except Exception as e:
            await status_msg.delete()
            embed = discord.Embed(
                description=f"❌ Lỗi khi tải playlist",
                color=0xED4245
            )
            await ctx.send(embed=embed)
    else:
        try:
            song_info = await search_youtube(query)
            await status_msg.delete()
            
            if song_info:
                if voice_clients[guild_id].is_playing():
                    queue = get_queue(guild_id)
                    queue.append(song_info)
                    
                    embed = discord.Embed(
                        title="",
                        description=f"### ➕ Đã thêm vào hàng đợi\n**[{song_info['title']}]({song_info['webpage_url']})**",
                        color=0x5865F2
                    )
                    embed.add_field(name="📍 Vị trí", value=f"`#{len(queue)}`", inline=True)
                    embed.add_field(name="⏱️ Thời lượng", value=f"`{format_duration(song_info['duration'])}`", inline=True)
                    embed.add_field(name="📺 Kênh", value=f"`{song_info.get('uploader', 'Unknown')}`", inline=True)
                    
                    if song_info['thumbnail']:
                        embed.set_thumbnail(url=song_info['thumbnail'])
                    
                    embed.set_footer(text=f"Yêu cầu bởi {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
                    
                    await ctx.send(embed=embed)
                else:
                    await play_song(ctx, song_info)
            else:
                embed = discord.Embed(
                    description="❌ Không tìm thấy bài hát hoặc quá thời gian chờ (20s)",
                    color=0xED4245
                )
                await ctx.send(embed=embed)
        except Exception as e:
            await status_msg.delete()
            embed = discord.Embed(
                description=f"❌ Lỗi không xác định khi tìm kiếm",
                color=0xED4245
            )
            await ctx.send(embed=embed)

@bot.command(name='stop', aliases=['s'])
async def stop(ctx):
    guild_id = ctx.guild.id
    if guild_id in voice_clients and voice_clients[guild_id].is_connected():
        voice_client = voice_clients[guild_id]
        
        try:
            await voice_client.channel.edit(status=None)
        except:
            pass
        
        if voice_client.is_playing():
            voice_client.stop()
        await voice_client.disconnect()
        del voice_clients[guild_id]
        
        if guild_id in queues:
            queues[guild_id].clear()
        if guild_id in current_songs:
            del current_songs[guild_id]
        if guild_id in alone_timers:
            alone_timers[guild_id].cancel()
            del alone_timers[guild_id]
        
        embed = discord.Embed(
            description="⏹️ Đã dừng phát nhạc và rời khỏi voice channel",
            color=0x5865F2
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            description="❌ Bot không ở trong voice channel",
            color=0xED4245
        )
        await ctx.send(embed=embed)

@bot.command(name='skip', aliases=['sk'])
async def skip(ctx):
    guild_id = ctx.guild.id
    if guild_id in voice_clients and voice_clients[guild_id].is_playing():
        voice_clients[guild_id].stop()
        embed = discord.Embed(
            description="⏭️ Đã skip sang bài tiếp theo",
            color=0x5865F2
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            description="❌ Không có bài hát đang phát",
            color=0xED4245
        )
        await ctx.send(embed=embed)

@bot.command(name='pause', aliases=['pa'])
async def pause(ctx):
    guild_id = ctx.guild.id
    if guild_id in voice_clients and voice_clients[guild_id].is_playing():
        voice_clients[guild_id].pause()
        embed = discord.Embed(
            description="⏸️ Đã tạm dừng phát nhạc",
            color=0x5865F2
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            description="❌ Không có bài hát đang phát",
            color=0xED4245
        )
        await ctx.send(embed=embed)

@bot.command(name='resume', aliases=['r'])
async def resume(ctx):
    guild_id = ctx.guild.id
    if guild_id in voice_clients and voice_clients[guild_id].is_paused():
        voice_clients[guild_id].resume()
        embed = discord.Embed(
            description="▶️ Đã tiếp tục phát nhạc",
            color=0x57F287
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            description="❌ Nhạc không bị tạm dừng",
            color=0xED4245
        )
        await ctx.send(embed=embed)

@bot.command(name='queue', aliases=['q'])
async def queue_cmd(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    current = get_current_song(guild_id)
    
    if not current and len(queue) == 0:
        embed = discord.Embed(
            description="📋 Queue trống. Sử dụng `b!play` để thêm nhạc!",
            color=0x5865F2
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="📋 Queue hiện tại",
        color=0x5865F2
    )
    
    if current:
        embed.add_field(
            name="🎵 Đang phát",
            value=f"**[{current['title']}]({current['webpage_url']})**\n`{format_duration(current['duration'])}` • `{current.get('uploader', 'Unknown')}`",
            inline=False
        )
    
    if len(queue) > 0:
        queue_text = ""
        total_duration = sum(song.get('duration', 0) for song in queue)
        
        for i, song in enumerate(list(queue)[:10], 1):
            duration = format_duration(song.get('duration', 0))
            title = song.get('title', 'Unknown')
            url = song.get('webpage_url', song.get('url', ''))
            queue_text += f"`{i}.` **[{title}]({url})** - `{duration}`\n"
        
        if len(queue) > 10:
            queue_text += f"\n*...và {len(queue) - 10} bài hát khác*"
        
        embed.add_field(
            name=f"📑 Tiếp theo • {len(queue)} bài hát • {format_duration(total_duration)}",
            value=queue_text,
            inline=False
        )
    
    loop = get_loop_mode(guild_id)
    if loop == 1:
        embed.set_footer(text="🔂 Loop: Bài hát hiện tại")
    elif loop == 2:
        embed.set_footer(text="🔁 Loop: Queue")
    
    await ctx.send(embed=embed)

@bot.command(name='clear', aliases=['cl'])
async def clear(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    count = len(queue)
    queue.clear()
    
    embed = discord.Embed(
        description=f"🗑️ Đã xóa **{count}** bài hát khỏi queue",
        color=0x5865F2
    )
    await ctx.send(embed=embed)

@bot.command(name='loop', aliases=['l'])
async def loop_cmd(ctx, mode: str = None):
    guild_id = ctx.guild.id
    
    if mode is None:
        current_loop = get_loop_mode(guild_id)
        if current_loop == 0:
            set_loop_mode(guild_id, 2)
            embed = discord.Embed(description="🔁 Đã bật loop cho toàn bộ queue", color=0x57F287)
        elif current_loop == 2:
            set_loop_mode(guild_id, 1)
            embed = discord.Embed(description="🔂 Đã bật loop cho bài hát hiện tại", color=0x57F287)
        else:
            set_loop_mode(guild_id, 0)
            embed = discord.Embed(description="➡️ Đã tắt loop", color=0x5865F2)
    else:
        if mode.lower() in ['off', '0']:
            set_loop_mode(guild_id, 0)
            embed = discord.Embed(description="➡️ Đã tắt loop", color=0x5865F2)
        elif mode.lower() in ['song', '1', 'current']:
            set_loop_mode(guild_id, 1)
            embed = discord.Embed(description="🔂 Đã bật loop cho bài hát hiện tại", color=0x57F287)
        elif mode.lower() in ['queue', '2', 'all']:
            set_loop_mode(guild_id, 2)
            embed = discord.Embed(description="🔁 Đã bật loop cho toàn bộ queue", color=0x57F287)
        else:
            embed = discord.Embed(description="❌ Mode không hợp lệ. Dùng: `off`, `song`, `queue`", color=0xED4245)
    
    await ctx.send(embed=embed)

@bot.command(name='volume', aliases=['v', 'vol'])
async def volume(ctx, vol: int = None):
    guild_id = ctx.guild.id
    
    if vol is None:
        current_vol = int(get_volume(guild_id) * 100)
        embed = discord.Embed(
            description=f"🔊 Volume hiện tại: **{current_vol}%**",
            color=0x5865F2
        )
        await ctx.send(embed=embed)
        return
    
    if vol < 0 or vol > 200:
        embed = discord.Embed(
            description="❌ Volume phải từ 0 đến 200",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    volume_decimal = vol / 100
    set_volume(guild_id, volume_decimal)
    
    if guild_id in voice_clients and voice_clients[guild_id].is_playing():
        voice_clients[guild_id].source.volume = volume_decimal
    
    embed = discord.Embed(
        description=f"🔊 Đã thay đổi volume thành **{vol}%**",
        color=0x57F287
    )
    await ctx.send(embed=embed)

@bot.command(name='nowplaying', aliases=['np'])
async def nowplaying(ctx):
    guild_id = ctx.guild.id
    current = get_current_song(guild_id)
    
    if not current:
        embed = discord.Embed(
            description="❌ Không có bài hát đang phát",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="",
        description=f"### 🎵 Đang phát\n**[{current['title']}]({current['webpage_url']})**",
        color=0x5865F2
    )
    embed.add_field(name="⏱️ Thời lượng", value=f"`{format_duration(current['duration'])}`", inline=True)
    embed.add_field(name="📺 Kênh", value=f"`{current.get('uploader', 'Unknown')}`", inline=True)
    
    loop = get_loop_mode(guild_id)
    if loop == 1:
        embed.add_field(name="🔁 Loop", value="`Bài hát`", inline=True)
    elif loop == 2:
        embed.add_field(name="🔁 Loop", value="`Queue`", inline=True)
    else:
        embed.add_field(name="🔁 Loop", value="`Tắt`", inline=True)
    
    vol = int(get_volume(guild_id) * 100)
    embed.add_field(name="🔊 Volume", value=f"`{vol}%`", inline=True)
    
    queue_length = len(get_queue(guild_id))
    if queue_length > 0:
        embed.add_field(name="📋 Tiếp theo", value=f"`{queue_length} bài`", inline=True)
    
    if current['thumbnail']:
        embed.set_thumbnail(url=current['thumbnail'])
    
    await ctx.send(embed=embed)

@bot.command(name='remove', aliases=['rm'])
async def remove(ctx, index: int):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    
    if index < 1 or index > len(queue):
        embed = discord.Embed(
            description=f"❌ Vị trí không hợp lệ. Queue có **{len(queue)}** bài hát",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    queue_list = list(queue)
    removed_song = queue_list[index - 1]
    queue_list.pop(index - 1)
    queues[guild_id] = deque(queue_list)
    
    embed = discord.Embed(
        description=f"🗑️ Đã xóa: **{removed_song['title']}**",
        color=0x5865F2
    )
    await ctx.send(embed=embed)

@bot.command(name='shuffle', aliases=['sh'])
async def shuffle(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    
    if len(queue) < 2:
        embed = discord.Embed(
            description="❌ Queue cần ít nhất 2 bài hát để shuffle",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    import random
    queue_list = list(queue)
    random.shuffle(queue_list)
    queues[guild_id] = deque(queue_list)
    
    embed = discord.Embed(
        description=f"🔀 Đã shuffle **{len(queue)}** bài hát",
        color=0x57F287
    )
    await ctx.send(embed=embed)

@bot.command(name='help', aliases=['h'])
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🎵 BensMusic - Hướng dẫn sử dụng",
        description="Bot phát nhạc chất lượng cao cho Discord",
        color=0x5865F2
    )
    
    embed.add_field(
        name="▶️ Phát nhạc",
        value=(
            "`b!play <tên/link>` `(p)` - Phát nhạc từ YouTube\n"
            "`b!pause` `(pa)` - Tạm dừng phát nhạc\n"
            "`b!resume` `(r)` - Tiếp tục phát nhạc\n"
            "`b!skip` `(sk)` - Bỏ qua bài hiện tại\n"
            "`b!stop` `(s)` - Dừng và rời voice channel"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📋 Quản lý Queue",
        value=(
            "`b!queue` `(q)` - Xem queue hiện tại\n"
            "`b!clear` `(cl)` - Xóa toàn bộ queue\n"
            "`b!remove <số>` `(rm)` - Xóa bài cụ thể\n"
            "`b!shuffle` `(sh)` - Shuffle queue\n"
            "`b!move <từ> <đến>` `(mv)` - Di chuyển bài hát"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🔁 Loop & Âm lượng",
        value=(
            "`b!loop [mode]` `(l)` - Chế độ loop\n"
            "`b!volume <0-200>` `(v)` - Điều chỉnh volume\n"
            "`b!nowplaying` `(np)` - Bài đang phát"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎯 Nâng cao",
        value=(
            "`b!search <từ khóa>` `(sr)` - Tìm kiếm nhạc\n"
            "`b!playnext <query>` `(pn)` - Thêm vào đầu queue\n"
            "`b!playskip <query>` `(ps)` - Phát ngay lập tức\n"
            "`b!skipto <số>` `(st)` - Chuyển đến bài cụ thể\n"
            "`b!grab` `(save)` - Lưu bài hát vào DM"
        ),
        inline=False
    )
    
    embed.set_footer(text="Prefix: b! | BensMusic", icon_url=bot.user.avatar.url if bot.user.avatar else None)
    embed.timestamp = discord.utils.utcnow()
    
    await ctx.send(embed=embed)

@bot.command(name='join', aliases=['j', 'connect'])
async def join(ctx):
    if not ctx.author.voice:
        embed = discord.Embed(
            description="❌ Bạn phải ở trong voice channel!",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    channel = ctx.author.voice.channel
    guild_id = ctx.guild.id
    
    if guild_id in voice_clients and voice_clients[guild_id].is_connected():
        embed = discord.Embed(
            description="❌ Bot đã kết nối trong voice channel rồi!",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    voice_client = await channel.connect()
    voice_clients[guild_id] = voice_client
    await check_alone_in_channel(guild_id)
    
    embed = discord.Embed(
        description=f"✅ Đã tham gia **{channel.name}**",
        color=0x57F287
    )
    await ctx.send(embed=embed)

@bot.command(name='leave', aliases=['dc', 'disconnect'])
async def leave(ctx):
    guild_id = ctx.guild.id
    
    if guild_id not in voice_clients or not voice_clients[guild_id].is_connected():
        embed = discord.Embed(
            description="❌ Bot không ở trong voice channel",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    voice_client = voice_clients[guild_id]
    
    try:
        await voice_client.channel.edit(status=None)
    except:
        pass
    
    if voice_client.is_playing():
        voice_client.stop()
    await voice_client.disconnect()
    del voice_clients[guild_id]
    
    if guild_id in queues:
        queues[guild_id].clear()
    if guild_id in current_songs:
        del current_songs[guild_id]
    if guild_id in alone_timers:
        alone_timers[guild_id].cancel()
        del alone_timers[guild_id]
    
    embed = discord.Embed(
        description="👋 Đã rời khỏi voice channel",
        color=0x5865F2
    )
    await ctx.send(embed=embed)

@bot.command(name='skipto', aliases=['st'])
async def skipto(ctx, index: int):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    
    if index < 1 or index > len(queue):
        embed = discord.Embed(
            description=f"❌ Vị trí không hợp lệ. Queue có **{len(queue)}** bài hát",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    queue_list = list(queue)
    for i in range(index - 1):
        queue_list.pop(0)
    queues[guild_id] = deque(queue_list)
    
    if guild_id in voice_clients and voice_clients[guild_id].is_playing():
        voice_clients[guild_id].stop()
    
    embed = discord.Embed(
        description=f"⏭️ Đã chuyển đến bài hát **#{index}**",
        color=0x57F287
    )
    await ctx.send(embed=embed)

@bot.command(name='move', aliases=['mv'])
async def move(ctx, from_pos: int, to_pos: int):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    
    if from_pos < 1 or from_pos > len(queue) or to_pos < 1 or to_pos > len(queue):
        embed = discord.Embed(
            description=f"❌ Vị trí không hợp lệ. Queue có **{len(queue)}** bài hát",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    queue_list = list(queue)
    song = queue_list.pop(from_pos - 1)
    queue_list.insert(to_pos - 1, song)
    queues[guild_id] = deque(queue_list)
    
    embed = discord.Embed(
        description=f"↔️ Đã di chuyển **{song['title']}** từ vị trí **{from_pos}** → **{to_pos}**",
        color=0x57F287
    )
    await ctx.send(embed=embed)

@bot.command(name='search', aliases=['sr'])
async def search(ctx, *, query: str):
    def _sync_search(query_str):
        ydl_opts = {
            'format': 'bestaudio*',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch5',
            'extract_flat': True,
            'nocheckcertificate': True,
            'source_address': '0.0.0.0',
            'socket_timeout': 10,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch5:{query_str}", download=False)
            if 'entries' in info:
                return info['entries'][:5]
            return []
    
    embed = discord.Embed(
        description=f"🔍 Đang tìm kiếm **{query}**...",
        color=0x5865F2
    )
    status_msg = await ctx.send(embed=embed)
    
    loop = asyncio.get_event_loop()
    try:
        results = await asyncio.wait_for(
            loop.run_in_executor(executor, _sync_search, query),
            timeout=15.0
        )
        
        await status_msg.delete()
        
        if results:
            embed = discord.Embed(
                title=f"🔍 Kết quả tìm kiếm: {query}",
                description="Sử dụng `b!play <link>` để phát bài hát",
                color=0x5865F2
            )
            
            for i, result in enumerate(results, 1):
                title = result.get('title', 'Unknown')
                duration = format_duration(result.get('duration', 0))
                url = f"https://youtube.com/watch?v={result.get('id', '')}"
                uploader = result.get('uploader', 'Unknown')
                embed.add_field(
                    name=f"{i}. {title}",
                    value=f"[▶️ Phát ngay]({url}) • `{duration}` • `{uploader}`",
                    inline=False
                )
            
            embed.set_footer(text="Nhấn vào link để xem trên YouTube")
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description="❌ Không tìm thấy kết quả",
                color=0xED4245
            )
            await ctx.send(embed=embed)
    except asyncio.TimeoutError:
        await status_msg.delete()
        embed = discord.Embed(
            description="❌ Quá thời gian tìm kiếm",
            color=0xED4245
        )
        await ctx.send(embed=embed)
    except Exception as e:
        await status_msg.delete()
        embed = discord.Embed(
            description=f"❌ Lỗi khi tìm kiếm",
            color=0xED4245
        )
        await ctx.send(embed=embed)

@bot.command(name='removedupes', aliases=['rd'])
async def removedupes(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    
    if len(queue) < 2:
        embed = discord.Embed(
            description="❌ Queue cần ít nhất 2 bài hát",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    queue_list = list(queue)
    seen = set()
    unique_queue = []
    removed_count = 0
    
    for song in queue_list:
        song_id = song.get('webpage_url', song.get('url', ''))
        if song_id not in seen:
            seen.add(song_id)
            unique_queue.append(song)
        else:
            removed_count += 1
    
    queues[guild_id] = deque(unique_queue)
    
    embed = discord.Embed(
        description=f"🗑️ Đã xóa **{removed_count}** bài hát trùng lặp",
        color=0x57F287
    )
    await ctx.send(embed=embed)

@bot.command(name='grab', aliases=['save'])
async def grab(ctx):
    guild_id = ctx.guild.id
    current = get_current_song(guild_id)
    
    if not current:
        embed = discord.Embed(
            description="❌ Không có bài hát đang phát",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    try:
        dm_embed = discord.Embed(
            title="💾 Bài hát đã lưu",
            description=f"**[{current['title']}]({current['webpage_url']})**",
            color=0x57F287
        )
        dm_embed.add_field(name="⏱️ Thời lượng", value=f"`{format_duration(current['duration'])}`", inline=True)
        dm_embed.add_field(name="📺 Kênh", value=f"`{current.get('uploader', 'Unknown')}`", inline=True)
        if current['thumbnail']:
            dm_embed.set_thumbnail(url=current['thumbnail'])
        dm_embed.set_footer(text=f"Từ server: {ctx.guild.name}")
        
        await ctx.author.send(embed=dm_embed)
        
        embed = discord.Embed(
            description="✅ Đã gửi bài hát vào DM của bạn!",
            color=0x57F287
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        embed = discord.Embed(
            description="❌ Không thể gửi DM. Vui lòng bật DM từ server members",
            color=0xED4245
        )
        await ctx.send(embed=embed)

@bot.command(name='playskip', aliases=['ps'])
async def playskip(ctx, *, query: str):
    if not ctx.author.voice:
        embed = discord.Embed(
            description="❌ Bạn phải ở trong voice channel!",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    channel = ctx.author.voice.channel
    guild_id = ctx.guild.id
    
    if guild_id not in voice_clients or not voice_clients[guild_id].is_connected():
        voice_client = await channel.connect()
        voice_clients[guild_id] = voice_client
        await check_alone_in_channel(guild_id)
    
    embed = discord.Embed(
        description=f"🔍 Đang tìm kiếm **{query}**...",
        color=0x5865F2
    )
    status_msg = await ctx.send(embed=embed)
    
    song_info = await search_youtube(query)
    await status_msg.delete()
    
    if song_info:
        if voice_clients[guild_id].is_playing():
            voice_clients[guild_id].stop()
        
        queue = get_queue(guild_id)
        queue_list = list(queue)
        queue_list.insert(0, song_info)
        queues[guild_id] = deque(queue_list)
        
        embed = discord.Embed(
            title="",
            description=f"### ⏭️ Play Skip\n**[{song_info['title']}]({song_info['webpage_url']})**",
            color=0x57F287
        )
        embed.add_field(name="⏱️ Thời lượng", value=f"`{format_duration(song_info['duration'])}`", inline=True)
        embed.add_field(name="📺 Kênh", value=f"`{song_info.get('uploader', 'Unknown')}`", inline=True)
        if song_info['thumbnail']:
            embed.set_thumbnail(url=song_info['thumbnail'])
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            description="❌ Không tìm thấy bài hát",
            color=0xED4245
        )
        await ctx.send(embed=embed)

@bot.command(name='playnext', aliases=['pn'])
async def playnext(ctx, *, query: str):
    if not ctx.author.voice:
        embed = discord.Embed(
            description="❌ Bạn phải ở trong voice channel!",
            color=0xED4245
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        description=f"🔍 Đang tìm kiếm **{query}**...",
        color=0x5865F2
    )
    status_msg = await ctx.send(embed=embed)
    
    song_info = await search_youtube(query)
    await status_msg.delete()
    
    if song_info:
        guild_id = ctx.guild.id
        queue = get_queue(guild_id)
        queue_list = list(queue)
        queue_list.insert(0, song_info)
        queues[guild_id] = deque(queue_list)
        
        embed = discord.Embed(
            title="",
            description=f"### ⏭️ Đã thêm vào đầu queue\n**[{song_info['title']}]({song_info['webpage_url']})**",
            color=0x57F287
        )
        embed.add_field(name="📍 Vị trí", value="`#1`", inline=True)
        embed.add_field(name="⏱️ Thời lượng", value=f"`{format_duration(song_info['duration'])}`", inline=True)
        embed.add_field(name="📺 Kênh", value=f"`{song_info.get('uploader', 'Unknown')}`", inline=True)
        if song_info['thumbnail']:
            embed.set_thumbnail(url=song_info['thumbnail'])
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            description="❌ Không tìm thấy bài hát",
            color=0xED4245
        )
        await ctx.send(embed=embed)

@bot.command(name='info', aliases=['stats', 'botinfo'])
async def info(ctx):
    guild_count = len(bot.guilds)
    total_users = sum(guild.member_count for guild in bot.guilds)
    
    embed = discord.Embed(
        title="ℹ️ BensMusic Information",
        description="Bot phát nhạc Discord chất lượng cao",
        color=0x5865F2
    )
    embed.add_field(name="📊 Servers", value=f"`{guild_count}`", inline=True)
    embed.add_field(name="👥 Users", value=f"`{total_users}`", inline=True)
    embed.add_field(name="⚡ Latency", value=f"`{round(bot.latency * 1000)}ms`", inline=True)
    embed.add_field(name="🔧 Prefix", value="`b!`", inline=True)
    embed.add_field(name="📚 Library", value="`discord.py`", inline=True)
    embed.add_field(name="🎵 Audio", value="`512kbps HQ`", inline=True)
    embed.set_footer(text="BensMusic v2.1")
    embed.timestamp = discord.utils.utcnow()
    
    await ctx.send(embed=embed)

@bot.command(name='ping')
async def ping(ctx):
    latency = round(bot.latency * 1000)
    
    embed = discord.Embed(
        description=f"🏓 Pong! Latency: **{latency}ms**",
        color=0x57F287
    )
    await ctx.send(embed=embed)

@bot.command(name='invite')
async def invite(ctx):
    embed = discord.Embed(
        title="📨 Mời BensMusic",
        description="Cảm ơn bạn đã quan tâm đến BensMusic!",
        color=0x5865F2
    )
    embed.add_field(
        name="🔗 Link mời bot",
        value="https://discord.com/api/oauth2/authorize?client_id=1414584931274854400&permissions=36700160&scope=bot",
        inline=False
    )
    embed.set_footer(text="BensMusic v2.1")
    
    await ctx.send(embed=embed)

@bot.command(name='support')
async def support(ctx):
    embed = discord.Embed(
        title="💬 Hỗ trợ & Liên hệ",
        description="Cần hỗ trợ? Liên hệ với chúng tôi!",
        color=0x5865F2
    )
    embed.add_field(
        name="🌐 Discord Server",
        value="[Join Support Server](https://discord.gg/KY5uDEBeJ4)",
        inline=False
    )
    embed.add_field(
        name="💻 GitHub",
        value="[View Source Code](https://github.com/BensG0ming/BensMusic)",
        inline=False
    )
    embed.set_footer(text="BensMusic v2.1")
    
    await ctx.send(embed=embed)

@bot.event
async def on_disconnect():
    executor.shutdown(wait=False)

bot.run('DEO_CO_TOKEN')
