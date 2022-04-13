# Alex Helpful Aliases
alias docker-killall='docker container stop $(docker container ls -aq) && docker container rm $(docker container ls -aq)'
alias grepnt="grep --invert-match"
alias highlight='grep --color=always -z'
export PS1="\[$(tput bold)\]\[\033[38;5;10m\]\u@\h\[$(tput sgr0)\]: \[$(tput sgr0)\]\[$(tput bold)\]\[\033[38;5;14m\]\w\[$(tput sgr0)\]\n⚔️  \[$(tput sgr0)\]"

