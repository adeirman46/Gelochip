* merge ac+tran plots into one viewing raw
.control
load /home/irman/pandachip/designs/lna/lna_final_ac.raw
load /home/irman/pandachip/designs/lna/lna_final_tran.raw
set filetype=binary
setplot ac1
set appendwrite
write /home/irman/pandachip/designs/lna/lna_view.raw
setplot tran1
write /home/irman/pandachip/designs/lna/lna_view.raw
quit
.endc
