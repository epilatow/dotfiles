" Erase pre-existing autocmds.
autocmd!

" Safer saves on FUSE/Cryptomator/Dropbox mounts
set backup                 " keep a backup file
set writebackup            " make a backup *during* every write
set backupext=~            " foo.txt~ stays around
set backupcopy=yes         " copy+overwrite (no rename trick)
set fsync                  " call fsync() after writing

" Keep swap/undo OFF of Cryptomator mounts (use local disk)
set directory=~/.vim/swap//
set undofile
set undodir=~/.vim/undo//

" enable multibyte support
set encoding=utf-8

" None of those annoying bells
set visualbell
set noerrorbells

" Enable modeline support (ie, read vim directives from target files)
set modeline modelines=1024

" set the default shell
set shell=/bin/bash

" Don't constantly fsync() the swap file
" Also, save swap files locally in /var/tmp
set swapsync=
set directory=/var/tmp

" Always show the status line with ruler.
set laststatus=2 ruler showmode

" File suffixes to ignore for editing selection (via :e).
set suffixes=.aux,.dvi,.gz,.idx,.log,.ps,.swp,.tar,.tgz,~

" Treat . [ * special in patterns
set magic

" Show matching (), {}, [] pairs
set showmatch

" avoid most the |hit-enter| command-line prompts.
"   a - Use status bar abbreviations.
"   I - Don't show me the begware screen.
"   t - truncate file message if they don't fit on the command-line
"   T - truncate other messages if they don't fit on the command-line
set shortmess=aItT

" use interactive search
set is
" enable search highlighting
set hlsearch

" Keep 50 commands in the history
set history=50

" Don't wrap text automatically
set textwidth=72

" set gui options
set guioptions-=T		" Disable toolbar
set guioptions-=m		" Disable menubar
set guioptions+=r		" Scrolbar on right
set guioptions-=l		" Scrolbar on right
set guifont=6x10		" set a smaller font

"
" Use syntax highlighting and filetyping.
" For some reason we need to enable syntax hilighting before we
" start to define colors if we want them to take.
"
if filereadable($VIMRUNTIME . "/syntax/syntax.vim")
    syntax on
else
    echo "syntax hilighting disabled. "
        \"($VIMRUNTIME/syntax/syntax.vim not found.)"
endif

" reset hilighting scheme to default
highlight clear
" set background=dark

" make the status line reverse and bold
set highlight=srb

"if filereadable($VIMRUNTIME . "/colors/pablo.vim") "   " colo desert "   colo pablo
"else
"   echo "default color scheme not loaded. "
"       \"($VIMRUNTIME/color/pablo.vim not found.)"
"endif

" set highlightling colours
"hi Comment      term=bold       guifg=rosybrown gui=NONE        ctermfg=6
"hi Constant     term=underline  guifg=wheat4    gui=NONE
"hi Cursor       guifg=grey30
"hi Directory    guifg=blue
"hi ErrorMsg     guifg=red4
"hi Identifier   term=underline  guifg=wheat4    gui=NONE
"hi IncSearch    guifg=blue
"hi LineNr       guifg=green3
"hi ModeMsg      guifg=blue
"hi MoreMsg      guifg=blue
"hi NonText      guifg=grey77
"hi Normal       guifg=black
"hi PreProc      term=underline  guifg=thistle4  gui=NONE
"hi Question     guifg=sienna
"hi Search       guifg=purple
"hi Special      term=bold       guifg=salmon3 gui=NONE
"hi SpecialKey   guifg=blue
"hi Statement    term=bold       guifg=grey20    gui=bold
"hi StatusLine   guifg=lightyellow4
"hi StatusLineNC guifg=grey10
"hi Title        guifg=lightyellow4
"hi Type         term=underline  guifg=tan4      gui=NONE
"hi Visual       guifg=green4
"hi VisualNOS    guifg=green4
"hi WarningMsg   guifg=red
"hi WildMenu     guifg=red

" Key bindings - cleanup trailing whitespace
map [c :%s/[ \t][ \t]*$//e

" Key bindings - fix cut and paste GUI_showtabs cruft
map [f :%s/¬/\t/eg:%s/·//eg

" Key bindings - Toggle paste mode
map  :set invpaste<CR>

" Key bindings - Spell checker
" map  :w!:!aspell check %:e! %
" map  :w!:!ispell -x %:e! %
" vim 7.x has built in spell checking
set spellfile=$HOME/.vim.spellfile.utf-8.add
map  :setlocal invspell spelllang=en_us
map  :setlocal spellcapcheck=""
"map  :setlocal spellcapcheck=[.?!]\\_[\\])'\"\	\ ]\\+

" Key bindings - Buffer list shortcuts
nmap [b :buffers<C-m>:buffer
nmap [d :buffers<C-m>:bdelete

" Emacs-like auto-indent for C (only indent when I hit tab in column 0)
set cinkeys=0{,0},:,0#,!0<Tab>,!^F

" Keep return types <t> and parameters <p> in K&R-style C at the left edge <0>
" Indent continuation lines/lines with unclosed parens 4 spaces <+4,(4,u4,U1>
" Don't indent case labels within a switch <:0>
set cinoptions=p0,t0,+4,(4,u4,U1,:0

" Default BufEnter action.
" NOTE:	this action must be declared first because later cmds will
"	override these default settings
autocmd BufEnter * setlocal fo=tcql nocindent autoindent comments& listchars& list&

" ensure that Makefiles are all using the make syntax highlighting
" (and not based on their suffix).
autocmd BufRead Makefile*,makefile* so $VIMRUNTIME/syntax/make.vim

" Text wrapping is a little earlier than 80 characters
autocmd BufEnter README,NOTES,*.html,*.lt?,*.tex,*.[0-9]*,*.man setlocal tw=72 autoindent

" Mail composition wrapping is a little earlier than 80 characters
autocmd BufEnter /tmp/mutt-* setlocal tw=72

" Activate C indenting and comment formatting when editing C or C++
autocmd BufEnter *.cc,*.c,*.h setlocal tw=80 fo=croq cindent

" For Python; use space based indentation
autocmd FileType python setlocal expandtab shiftwidth=4 softtabstop=4 tw=88

" Work around my bad vi habits to save files repeatedly
cabbr w0 w
cabbr :w %

"
" cindent options
"
" defaults:cinoptions=>s,e0,n0,f0,{0,}0,^0,:s,=s,l0,gs,hs,ps,ts,+s,c3,C0,(2s,us,
"                  \U0,w0,m0,j0,)20,*30
"
"       :0      - indentation of case labels matches switch
"       t0      - function return type is not indented
"       +.5s    - continuation lines indented by 1/2 shiftwidth
"       (0      - try to avoid extra indent during uncloses paranthesis
:set cinoptions=>8,e0,n0,f0,{0,}0,^0,:4,=4,p2,t2,+4,(4,)20,*30

if executable("cscope") && filereadable(expand("~/.vimrc.cscope"))
    source ~/.vimrc.cscope
endif
if has("eval") && filereadable(expand("~/.vimrc.eval"))
    source ~/.vimrc.eval
endif
