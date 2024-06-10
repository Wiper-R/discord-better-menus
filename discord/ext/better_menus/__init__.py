# pyright: strict

from abc import ABC, abstractmethod
from enum import IntEnum
import math
import discord
from discord.ext import commands
from typing import Any, AsyncIterator, Dict, Generic, Optional, TypeVar, List, Self

T = TypeVar("T")
Context = commands.Context[commands.Bot]

class MenusException(discord.DiscordException):
    """Base exception class for menu-related errors."""
    pass

class NothingOnThatPage(MenusException):
    """Raised when attempting to access a page that has no entries."""
    pass

class PageGoTo(IntEnum):
    """Enumeration of page navigation options."""
    FIRST_PAGE = 1
    LAST_PAGE = 2
    NEXT_PAGE = 3
    PREVIOUS_PAGE = 4
    CURRENT_PAGE = 5

class PageSource(ABC, Generic[T]):
    """Abstract base class for defining page sources."""

    def __init__(self, per_page: int, current_page: int = 0) -> None:
        """
        Initialize the PageSource.

        Args:
            per_page: Number of items per page.
            current_page: The current page number.
        """
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
        """Prepares a page before sending.

        Args:
            index: The page index to prepare.

        Returns:
            The formatted page.

        Raises:
            NothingOnThatPage: If the page has no entries.
        """
        page = await self.get_page(index)

        if not page or len(page) == 0:
            raise NothingOnThatPage

        page = await self.format_page(page)
        self.current_page = index
        return page

class ListPageSource(PageSource[T]):
    """A concrete implementation of PageSource for handling lists."""

    def __init__(self, entries: List[T], per_page: int) -> None:
        """
        Initialize the ListPageSource.

        Args:
            entries: The list of items.
            per_page: Number of items per page.
        """
        super().__init__(per_page)
        self.entries = entries

    async def get_page(self, page: int) -> List[T]:
        """Retrieve a specific page of data from the list.

        Args:
            page: The page number to retrieve.

        Returns:
            The list of items on the specified page.
        """
        start = page * self.per_page
        end = start + self.per_page
        return self.entries[start:end]

    async def format_page(self, page: List[T]) -> Any:
        """Format the retrieved page data.

        Args:
            page: The list of items on the page.

        Returns:
            The formatted page.
        """
        return "\n".join(str(entry) for entry in page)
    
    async def get_num_entries(self) -> int:
        """Get the total number of entries in the list.

        Returns:
            The total number of entries.
        """
        return len(self.entries)

class AsyncIteratorPageSource(PageSource[T]):
    """A concrete implementation of PageSource for handling asynchronous iterators."""

    def __init__(self, iterator: AsyncIterator[T], per_page: int) -> None:
        """
        Initialize the AsyncIteratorPageSource.

        Args:
            iterator: The asynchronous iterator of items.
            per_page: Number of items per page.
        """
        super().__init__(per_page)
        self.iterator = iterator
        self._cache: Dict[int, List[T]] = {}

    async def get_page(self, page: int) -> List[T]:
        """Retrieve a specific page of data from the asynchronous iterator.

        Args:
            page: The page number to retrieve.

        Returns:
            The list of items on the specified page.
        """
        if page < 0:
            return []

        if page in self._cache:
            return self._cache[page]

        data: List[T] = []
        counter = 0
        async for entry in self.iterator:
            data.append(entry)
            counter += 1
            if counter == self.per_page:
                break

        self._cache[page] = data
        return data

class Paginator(discord.ui.View):
    """A paginator for navigating through pages of items."""

    ctx: Context
    message: Optional[discord.Message]

    def __init__(self, source: PageSource[T], *, timeout: float | None = 180, allow_first_and_last: bool = False) -> None:
        """
        Initialize the Paginator.

        Args:
            source: The PageSource providing the data.
            timeout: The timeout for the paginator in seconds.
            allow_first_and_last: Whether to allow first and last page navigation.
        """
        super().__init__(timeout=timeout)
        self.source = source
        self.allow_first_and_last = allow_first_and_last
        self.message = None

    def fill_items(self, total_entries: int) -> None:
        """Fill the paginator with navigation buttons.

        Args:
            total_entries: The total number of entries.
        """
        if total_entries <= self.source.per_page:
            return
        
        visible_items = (self.source.current_page + 1) * self.source.per_page
        
        if self.allow_first_and_last:
            self.add_item(self.go_to_first_page)

            self.go_to_first_page.disabled = visible_items <= self.source.per_page

        self.add_item(self.go_to_previous_page)
        self.add_item(self.go_to_next_page)

        self.go_to_previous_page.disabled = self.source.current_page == 0
        self.go_to_next_page.disabled = visible_items >= total_entries

        if self.allow_first_and_last:
            self.add_item(self.go_to_last_page)

            self.go_to_last_page.disabled = visible_items >= total_entries

        self.add_item(self.quit_pagination)

    async def get_page_index(self, page: PageGoTo) -> int:
        """Get the index of the page to navigate to.

        Args:
            page: The PageGoTo enum indicating the page to navigate to.

        Returns:
            The index of the page.
        """
        if page == PageGoTo.CURRENT_PAGE:
            return self.source.current_page
        if page == PageGoTo.NEXT_PAGE:
            return self.source.current_page + 1
        if page == PageGoTo.PREVIOUS_PAGE:
            return self.source.current_page - 1
        if page == PageGoTo.LAST_PAGE:
            total_entries = await self.source.get_num_entries()
            return math.ceil(total_entries / self.source.per_page) - 1
        if page == PageGoTo.FIRST_PAGE:
            return 0
        
    async def send_page(self, interaction: Optional[discord.Interaction] = None, page: PageGoTo = PageGoTo.CURRENT_PAGE) -> None:
        """Send a page of items.

        Args:
            interaction: The Discord interaction.
            page: The PageGoTo enum indicating the page to navigate to.
        """
        interaction = interaction or self.ctx.interaction

        page_index = await self.get_page_index(page)
        formatted_page = await self.source.prepare_page(page_index)

        self.clear_items()
        total_entries = await self.source.get_num_entries()
        self.fill_items(total_entries)

        kwargs: Dict[str, Any]

        if isinstance(formatted_page, discord.Embed):
            kwargs = {"embed": formatted_page}
        else:
            kwargs = {"content": str(formatted_page)}

        if not self.message:
            self.message = await self.ctx.reply(**kwargs, view=self)
            return
        
        if interaction:
            await interaction.response.edit_message(**kwargs, view=self)

    async def quit(self) -> None:
        """Quit the pagination and disable all buttons."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        self.stop()

    @discord.ui.button(label="<<", style=discord.ButtonStyle.grey)
    async def go_to_first_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]) -> None:
        """Navigate to the first page."""
        await self.send_page(interaction, PageGoTo.FIRST_PAGE)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.blurple)
    async def go_to_previous_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]) -> None:
        """Navigate to the previous page."""
        await self.send_page(interaction, PageGoTo.PREVIOUS_PAGE)
    
    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def go_to_next_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]) -> None:
        """Navigate to the next page."""
        await self.send_page(interaction, PageGoTo.NEXT_PAGE)
    
    @discord.ui.button(label=">>", style=discord.ButtonStyle.grey)
    async def go_to_last_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]) -> None:
        """Navigate to the last page."""
        await self.send_page(interaction, PageGoTo.LAST_PAGE)

    @discord.ui.button(label="Quit", style=discord.ButtonStyle.red)
    async def quit_pagination(self, interaction: discord.Interaction, button: discord.ui.Button[Self]) -> None:
        """Quit the pagination."""
        await self.quit()
        await interaction.response.edit_message(view=self)
