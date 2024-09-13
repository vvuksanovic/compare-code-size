import os
import sys
import subprocess
import argparse
import pandas as pd
import numpy as np

CLEAR_LINE = '\x1b[2K'

# Output format (Berkeley):
# text    data     bss    dec     hex    filename
# 164       0       0     164      a4    libstubs.c.o (ex /home/syrmia/llvm-nanomips/llvm-test-suite-nanomips-build-1/libstubs.a)

def collectCodeSizeData(build_path, size_tool, size_tool_args) -> pd.DataFrame:

    build_abs_path = os.path.abspath(build_path)

    _, build_dir_name = os.path.split(build_abs_path)

    data = pd.DataFrame(columns=['text', 'data', 'bss', 'dec', 'hex', 'filename'])

    for root, dirs, files in os.walk(build_abs_path, followlinks=False):
        for file in files:

            # Skip object files
            file_root, file_base = os.path.split(file)
            ext = os.path.splitext(file_base)[1]
            if ext != '.o' and ext != '.a' and ext != '.so':
                # Check if file is executable
                file_processsRetVal = subprocess.run(["file", os.path.join(root, file)], capture_output=True)
                file_processsRetVal.check_returncode()
                file_output = file_processsRetVal.stdout.decode('utf-8')
                if file_output.find("ELF") == -1 or file_output.find("executable") == -1:
                    continue

            print(CLEAR_LINE + 'Processing ' + file_base, end='\r')

            processsRetVal = subprocess.run([size_tool] + size_tool_args + [os.path.join(root, file)],
                                            capture_output=True
                                           )
            # Skip all files with unrecognized format.
            if processsRetVal.returncode == 3:
                continue

            # Raise exception if other erros occured.
            # processsRetVal.check_returncode()
            if processsRetVal.returncode != 0:
                print("Size returned " + str(processsRetVal.returncode) + " for " + os.path.join(root, file), file=sys.stderr)
                continue

            # Get 'size' output as a string
            Output = processsRetVal.stdout.decode('utf-8')
            if "bss" not in Output or len(Output.split(sep='\n')) < 2:
                print("Invalid output for " + os.path.join(root, file) + ": " + Output, file=sys.stderr)
                continue

            values = []
            # Process output values into list
            for i, entry in enumerate(Output.split(sep='\n')[1].split('\t')):
                # used for filename entries
                index = entry.find(build_dir_name)
                if i in range(4):
                    # 'text', 'data', 'bss', 'dec'
                    values.append(int(entry))
                elif index != -1:
                    # 'filename'
                    values.append(entry[index+len(build_dir_name):])
                else:
                    # 'hex'
                    # [or filename without build_dir_name in it,
                    # but this should not happen becuse we are taking abs path
                    # hence calling size on abs path of files]
                    values.append(entry)

            # Append new row
            data.loc[len(data),] = values

    print(CLEAR_LINE, end='')
    return data

def parse_program_args():
    parser = argparse.ArgumentParser(description='Search for executables and generate code size diff.')
    parser.add_argument('directory_path_1', metavar='directory_path_1', action="store",
                    help="The first directory to search for executables.")
    parser.add_argument('directory_path_2', metavar='directory_path_2', action="store",
                help="The second directory to search for executables.")
    parser.add_argument('size_tool', metavar='size_tool', action="store", default='size',
                        help='path to size tool')
    parser.add_argument('size_tool_args', metavar='size_tool_args', action="store", nargs='*',
                        help='arguments for size tool')
    parser.add_argument('--show-plots', dest='show_plots', action="store_true", help='display chart with most changed files')
    return parser.parse_args()

def Main():
    args = parse_program_args()

    for i in range(len(args.size_tool_args)):
        if not args.size_tool_args[i].startswith("-") and args.size_tool_args[i-1] != '-o':
            args.size_tool_args[i] = "-" + args.size_tool_args[i]

    print("First  build -> data1: ", args.directory_path_1)
    print("Second build -> data2: ", args.directory_path_2)
    print("Size tool: ", args.size_tool)
    print("Size tool args: ", args.size_tool_args)

    file_command_result = subprocess.run(["file", "--version"], capture_output=True)
    if file_command_result.returncode != 0:
        print("Failed to run file command")
        exit(1)

    size_command_result = subprocess.run([args.size_tool, "--version"], capture_output=True)
    if size_command_result.returncode != 0:
        print("Failed to run size tool")
        exit(1)

    print('Collecting data for build 1')
    try:
        data1 = collectCodeSizeData(args.directory_path_1, args.size_tool, args.size_tool_args)
    except subprocess.CalledProcessError as e:
        print(e.returncode)
        exit()

    print('Collecting data for build 2')
    try:
        data2 = collectCodeSizeData(args.directory_path_2, args.size_tool, args.size_tool_args)
    except subprocess.CalledProcessError as e:
        print(e.returncode)
        exit()

    print("################ Results ################")
    print("data1 size: ", data1.shape[0])
    print("data2 size: ", data2.shape[0])

    # 'dec' = 'text' + 'data' + 'bss'
    code_size1 = data1['dec'].sum()
    code_size2 = data2['dec'].sum()

    if code_size1 > code_size2:
        print("We have savings in code size!")
    else:
        print("We have regression in code size!")
    print("Savings: ", code_size1 - code_size2, " bytes")

    savings_counter = 0
    regression_counter = 0
    for diff in data1['dec'] - data2['dec']:
        if diff < 0:
            regression_counter = regression_counter + 1
        elif diff > 0:
            savings_counter = savings_counter + 1
    print("We have savings in " + str(savings_counter) + " files." )
    print("We have regression in " + str(regression_counter) + " files." )
    print("###########################################")

    # Inner join data
    merged_data = pd.merge(data1, data2, on="filename", how="inner")

    # Calculate difference in size
    merged_data['diff'] = merged_data['dec_x'] - merged_data['dec_y']

    # Positive percentage means we have savings in size
    # Negative percentage means that the size is increase by that percentage
    merged_data['percentage'] = merged_data['diff'] * 100 / merged_data['dec_x']
    merged_data = merged_data.sort_values('percentage', ascending=False)

    positive_percentage_mask = np.array(list(merged_data['percentage'].astype(float))) > 0
    positive_percentage_num = positive_percentage_mask.sum()
    print("Num of percentage greater that zero: ", positive_percentage_num)

    show_plots = False

    if positive_percentage_num > 0:

        n = 20
        if positive_percentage_num < n:
            n = positive_percentage_num

        top_n_savings = merged_data.head(n)

        max_x_value = top_n_savings['dec_x'].astype(float).max()
    else:
        print("No saving in code size.")

    merged_data = merged_data.sort_values('percentage', ascending=True)

    negative_percentage_mask = np.array(list(merged_data['percentage'].astype(float))) < 0
    negative_percentage_num = negative_percentage_mask.sum()
    print("Num of percentage less that zero: ", negative_percentage_num)

    if negative_percentage_num > 0:

        n = 20
        if negative_percentage_num < n:
            n = negative_percentage_num

        top_n_regressions = merged_data.head(n)

        max_x_value = top_n_regressions['dec_x'].astype(float).max()


    else:
        print("No regressions in code size.")

    print(merged_data.to_string(), file=sys.stderr)


if __name__ == "__main__":
  Main()
