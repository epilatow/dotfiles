" Erase pre-existing autocmds.
autocmd!

" Use write in place (disable writing a new file and renaming)
"filesystems Required for Cryptomator FUSE-T mounts
set backupcopy=yes nowritebackup

" Write on buffer switch, write backup files to *~ files
set autowrite backup backupext=~

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

" Update xterminal titles.
if $CSCOPE_DB == ""
	set title
	set titleold=""
endif

" Show matching (), {}, [] pairs
set showmatch

" avoid most the |hit-enter| command-line prompts.
"	a - Use status bar abbreviations.
"	I - Don't show me the begware screen.
"	t - truncate file message if they don't fit on the command-line
"	T - truncate other messages if they don't fit on the command-line
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

"if filereadable($VIMRUNTIME . "/colors/pablo.vim")
"	" colo desert
"	colo pablo
"else
"	echo "default color scheme not loaded. "
"	    \"($VIMRUNTIME/color/pablo.vim not found.)"
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

function Tabify()
	let s:c_max = 120 " max number of virtual columns we will process

	" cleanup trailing whitespace
	:%s/[ \t][ \t]*$//e

	" fix cut and paste GUI_showtabs cruft
	:%s/¬/\t/eg
	:%s/·//eg

	" start processing at virtual column nunber 1
	let s:c = 1
	while s:c <= s:c_max

		"
		" replace any string of spaces with a tab iff:
		"
		" - the string is <= one tabstop in length and > two
		"   spaces in length (we don't want to convert the two
		"   spaces between sentences)
		"
		" - the string ends on a virtual column that is a multiple
		"   of the tabstop length
		"
		let s:l = &ts
		while s:l > 2
			exec ':%s/' . Spaces(s:l) . '\%' . s:c . 'v/\t/e'
			let s:l = s:l - 1
		endwhile

		"
		" replace any string of spaces with a tab iff:
		"
		" - the string is <= two spaces in length
		"
		" - the string is followed by a tab which is in a virtual
		"   column that is a multiple of the tabstop length
		"
		let s:l = 2
		while s:l > 0
			exec ':%s/' . Spaces(s:l) . '\t\%' . s:c . 'v/\t\t/e'
			let s:l = s:l - 1
		endwhile

		" increment the virtual column pointer by one tabstop length
		let s:c = s:c + &ts
	endwhile

endfun

function Spaces(x)
	let s:n = a:x
	let s:r = ""
	while s:n > 0
		let s:r = s:r . " "
		let s:n = s:n - 1
	endwhile
	return s:r
endfun

" Key bindings - cleanup trailing whitespace
map [c :%s/[ \t][ \t]*$//e

" Key bindings - fix cut and paste GUI_showtabs cruft
map [f :%s/¬/\t/eg:%s/·//eg

" Key bindings - Tabify spaces
map [t :call Tabify()

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

" Key bindings - cscope/tags support
map  :cscope find g <C-R>=expand("<cword>") " find definition
map  :cscope find s <C-R>=expand("<cword>") " find C symbol
map  :cscope find c <C-R>=expand("<cword>") " find callers
map  :cscope find t <C-R>=expand("<cword>") " find assignments

" cscope/tags support
"set cscopeverbose		" verbose option for debugging
"set cscopetag			" use :cstag instead of :tag for tags behavior
if executable("cscope-fast")	" use cscope-fast instead of regular cscope
	set cscopeprg=cscope-fast
	if has('cscoperelative')
		" prepend cscope db path to cscope file paths
		set cscoperelative
	endif
	if $CSCOPE_DB != ""
		" add database pointed to by environment
		if (stridx($CSCOPE_DB, "/usr/src/uts/cscope.out") >= 0)
			cscope add $CSCOPE_DB usr/src/uts
		elseif (stridx($CSCOPE_DB, "/usr/src/cscope.out") >= 0)
			cscope add $CSCOPE_DB usr/src
		else
			cscope add $CSCOPE_DB
		endif
	elseif filereadable("cscope.out")
		" else add database in current directory
		cscope add cscope.out
	endif
endif

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

" The list/listchars options cause the trailing spaces to be highlighted
" as an inverted question mark with my preferred font.
autocmd BufEnter *	call GUI_showtabs()
autocmd BufNewFile *	call GUI_showtabs()
autocmd BufRead *	call GUI_showtabs()

function! GUI_showtabs()
	set list listchars=tab:¬·,trail:¿
"	set list listchars=tab:>-,trail:<
endfun

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
autocmd BufEnter *.py setlocal expandtab tw=78

" For Python; use space based indentation
autocmd BufEnter *.java setlocal expandtab tw=78 ts=4

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

" rust.vim configuration
let g:rustfmt_autosave = 1
