# pyright: strict

from abc import ABC, abstractmethod
from enum import IntEnum
import math
import discord
from discord.ext import commands
from typing import Any, AsyncGenerator, Dict, Generic, Optional, Self, TypeVar, List

from discord.ui.item import Item


T = TypeVar("T")
Context = commands.Context[commands.Bot]

class MenusException(discord.DiscordException):
    pass


class NothingOnThatPage(MenusException):
    pass

class PageGoTo(IntEnum):
    first_page = 1
    last_page = 2
    next_page = 3
    previous_page = 4
    current_page = 5

class PageSource(ABC, Generic[T]):
    """Abstract base class for defining page sources."""

    def __init__(self, per_page: int, current_page: int = 0) -> None:
        self.per_page = per_page
        self.current_page = current_page

    @abstractmethod
    async def get_page(self, page: int) -> List[T]:
        """Retrieve a specific page of data."""
        pass

    @abstractmethod
    async def format_page(self, page: List[T]) -> Any:
        """Format the retrieved page data."""
        pass
    
    @abstractmethod
    async def get_num_entries(self) -> int:
        """Get the total number of entries."""
        pass

    async def prepare_page(self, index: int) -> Any:
        """Prepares page before sending."""
        page = await self.get_page(index)

        if not page or len(page) == 0:
            raise NothingOnThatPage

        page = await self.format_page(page)
        self.current_page = index
        return page


class GetPageSource(PageSource[T]):
    pass


class AsyncIteratorPageSource(PageSource[T]):
    def __init__(
        self, iterator: AsyncGenerator[T, None], per_page: int
    ) -> None:
        super().__init__(per_page)
        self.iterator = iterator
        self._cache: Dict[int, List[T]] = {}

    async def get_page(self, page: int) -> List[T]:
        if page < 0:
            return []

        try:
            return self._cache[page]
        except KeyError:
            pass

        data: List[T] = []
        counter = 0
        async for entry in self.iterator:
            data.append(entry)
            if counter == self.per_page - 1:
                break

            counter += 1

        self._cache[page] = data
        return data




class Paginator(discord.ui.View):
    ctx: Context
    message: Optional[discord.Message]

    def __init__(
        self,
        source: PageSource[T],
        *,
        timeout: float | None = 180,
        allow_first_and_last: bool = False,
    ):
        super().__init__(timeout=timeout)
        self.source = source
        self.allow_first_and_last = allow_first_and_last
        self.message = None


    def fill_items(self, entries: int) -> None:
        if entries <= self.source.per_page:
            return
        
        _visible = (self.source.current_page + 1) * self.source.per_page
        
        if self.allow_first_and_last:
            self.add_item(self.go_to_first_page)

            if _visible <= self.source.per_page:
                self.go_to_first_page.disabled = True
            else:
                self.go_to_first_page.disabled = False



        self.add_item(self.go_to_previous_page)
        self.add_item(self.go_to_next_page)

        if self.source.per_page < _visible:    
            self.go_to_previous_page.disabled = False
        else:
            self.go_to_previous_page.disabled = True

        if _visible < entries:
            self.go_to_next_page.disabled = False
        else:
            self.go_to_next_page.disabled = True

        if self.allow_first_and_last:
            self.add_item(self.go_to_last_page)

            if _visible >= entries:
                self.go_to_last_page.disabled = True
            else:
                self.go_to_last_page.disabled = False

        self.add_item(self.quit_pagination)



    async def get_go_to_index(self, page: PageGoTo) -> int:
        if page == PageGoTo.current_page:
            return self.source.current_page
        elif page == PageGoTo.next_page:
            return self.source.current_page + 1
        elif page == PageGoTo.previous_page:
            return self.source.current_page - 1
        elif page == PageGoTo.last_page:
            return math.ceil(await self.source.get_num_entries() / self.source.per_page) - 1
        elif page == PageGoTo.first_page:
            return 0
        
    async def send_page(self, interaction: Optional[discord.Interaction] = None, go_to: PageGoTo = PageGoTo.current_page):
        interaction = interaction or self.ctx.interaction


        pidx = await self.get_go_to_index(go_to)
        page = await self.source.prepare_page(pidx)

        self.clear_items()
        entries = await self.source.get_num_entries()
        self.fill_items(entries)



        kwargs: Dict[str, Any]

        if isinstance(page, discord.Embed):
            kwargs = {"embed": page}
        else:
            kwargs = {"content": str(page)}


        if not self.message:
            self.message = await self.ctx.send(**kwargs, view=self) 
        

        
        if interaction:
            await interaction.response.edit_message(**kwargs, view=self)   

    async def quit(self):
        # TODO: Maybe clear all buttons / or at least make those disable
        for item in self._children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        self.stop()

    @discord.ui.button(label="<<", style=discord.ButtonStyle.grey)
    async def go_to_first_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        await self.send_page(interaction, PageGoTo.first_page)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.blurple)
    async def go_to_previous_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        await self.send_page(interaction, PageGoTo.previous_page)
    
    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def go_to_next_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        await self.send_page(interaction, PageGoTo.next_page)
    
    
    @discord.ui.button(label=">>", style=discord.ButtonStyle.grey)
    async def go_to_last_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        await self.send_page(interaction, PageGoTo.last_page)

    @discord.ui.button(label="Quit", style=discord.ButtonStyle.red)
    async def  quit_pagination(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        await self.quit()
        await interaction.response.edit_message(view=self)

    async def start(self, ctx: Context):
        self.ctx = ctx
        await self.send_page()

    async def on_error(self, interaction: discord.Interaction[discord.Client], error: Exception, item: Item[Any]) -> None:
        return await super().on_error(interaction, error, item)
        

    async def interaction_check(self, interaction: discord.Interaction[discord.Client]) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        

        await interaction.response.send_message("This pagination doesn't belong to you.", ephemeral=True)
        return False