open_project -reset existing_dense_project
add_files existing_dense_project.cpp
add_files -tb testbench.cpp
set_top existing_dense_project
open_solution -reset "solution1"
set_part {xc7z020clg400-1}
create_clock -period 5 -name default
csim_design
csynth_design
exit

